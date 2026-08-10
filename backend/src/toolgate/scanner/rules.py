from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from toolgate.common.tool_definition import ToolDefinition
from toolgate.scanner.context import ScanContext
from toolgate.scanner.models import Finding, RuleId, Severity
from toolgate.scanner.unicode import classify_invisibles, mixed_script_confusable, reveal_invisible

Rule = Callable[[ToolDefinition, ScanContext], list[Finding]]

MAX_EVIDENCE = 160


@dataclass(frozen=True, slots=True)
class TextField:
    location: str
    text: str


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_EVIDENCE else text[: MAX_EVIDENCE - 1] + "…"


MAX_WALK_DEPTH = 40
MAX_WALK_NODES = 25_000

# Structural JSON Schema keywords and MCP annotation hints. Their names carry no prose, so they are not
# reported as text; any other key (property names, $defs names, vendor extensions) is scanned like a value.
_KNOWN_KEYS = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$anchor",
        "$dynamicRef",
        "$dynamicAnchor",
        "$vocabulary",
        "$comment",
        "$defs",
        "definitions",
        "type",
        "properties",
        "patternProperties",
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "required",
        "dependentRequired",
        "dependentSchemas",
        "items",
        "prefixItems",
        "additionalItems",
        "unevaluatedItems",
        "contains",
        "minContains",
        "maxContains",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "enum",
        "const",
        "default",
        "examples",
        "title",
        "description",
        "format",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "readOnly",
        "writeOnly",
        "deprecated",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "nullable",
        "readOnlyHint",
        "destructiveHint",
        "idempotentHint",
        "openWorldHint",
    }
)
_NAME_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
_PROPERTY_MAPS = frozenset({"properties", "patternProperties"})
_NESTING_KEYS = frozenset(
    {
        "properties",
        "patternProperties",
        "items",
        "prefixItems",
        "additionalProperties",
        "additionalItems",
        "unevaluatedProperties",
        "unevaluatedItems",
        "contains",
    }
)


@dataclass(frozen=True, slots=True)
class DefinitionWalk:
    fields: tuple[TextField, ...]
    property_names: tuple[tuple[str, str], ...]
    schema_depth: int
    truncated: bool


def walk_definition(tool: ToolDefinition) -> DefinitionWalk:
    """Every string a model could read, wherever an attacker put it: values, property names, annotations.

    Iterative with a depth and node budget, so a hostile, deeply nested schema cannot crash the scan; hitting
    the budget is itself reported.
    """
    fields = [TextField("name", tool.name), TextField("description", tool.description)]
    if tool.title:
        fields.append(TextField("title", tool.title))
    names: list[tuple[str, str]] = []
    roots: list[tuple[str, Any]] = [("inputSchema", tool.input_schema)]
    if tool.output_schema is not None:
        roots.append(("outputSchema", tool.output_schema))
    if tool.annotations:
        roots.append(("annotations", tool.annotations))

    # (path, node, json depth, schema nesting depth, name of the containing key)
    stack: list[tuple[str, Any, int, int, str | None]] = [(path, node, 0, 1, None) for path, node in reversed(roots)]
    max_schema_depth = 0
    visited = 0
    truncated = False
    while stack:
        path, node, depth, schema_depth, parent_key = stack.pop()
        visited += 1
        if depth > MAX_WALK_DEPTH or visited > MAX_WALK_NODES:
            truncated = True
            continue
        if isinstance(node, str):
            if node:
                fields.append(TextField(path, node))
            continue
        if isinstance(node, list):
            stack.extend(
                (f"{path}[{i}]", item, depth + 1, schema_depth, None) for i, item in reversed(list(enumerate(node)))
            )
            continue
        if not isinstance(node, Mapping):
            continue
        max_schema_depth = max(max_schema_depth, schema_depth)
        in_name_map = parent_key in _NAME_MAPS
        children: list[tuple[str, Any, int, int, str | None]] = []
        for key, value in node.items():
            name = str(key)
            child = f"{path}.{name}"
            if in_name_map or name not in _KNOWN_KEYS:
                fields.append(TextField(child, name))
            if parent_key in _PROPERTY_MAPS:
                names.append((name, child))
            nested = not in_name_map and name in _NESTING_KEYS
            children.append(
                (child, value, depth + 1, schema_depth + 1 if nested else schema_depth, None if in_name_map else name)
            )
        stack.extend(reversed(children))
    return DefinitionWalk(
        fields=tuple(f for f in fields if f.text),
        property_names=tuple(names),
        schema_depth=max_schema_depth,
        truncated=truncated,
    )


def text_fields(tool: ToolDefinition) -> list[TextField]:
    return list(walk_definition(tool).fields)


@dataclass(frozen=True, slots=True)
class Pattern:
    regex: re.Pattern[str]
    severity: Severity
    title: str


def _p(expr: str, severity: Severity, title: str) -> Pattern:
    return Pattern(re.compile(expr, re.IGNORECASE | re.DOTALL), severity, title)


HIDDEN_INSTRUCTION_PATTERNS: tuple[Pattern, ...] = (
    _p(
        r"\b(ignore|disregard|forget|override)\b.{0,30}\b(all|any|previous|prior|above|earlier|system)\b"
        r".{0,20}\b(instructions?|prompts?|rules|guidelines)\b",
        Severity.CRITICAL,
        "Attempts to override prior instructions",
    ),
    _p(
        r"\b(do not|don't|never|without)\b.{0,25}\b(tell|telling|mention|mentioning|inform|informing|reveal|"
        r"revealing|notify|notifying|alert|alerting|show|showing)\b.{0,20}\b(the )?(user|human|operator)\b",
        Severity.CRITICAL,
        "Instructs the model to hide actions from the user",
    ),
    _p(
        r"\b(user|human)\b.{0,20}\b(must not|should not|shouldn't|won't|will not)\b.{0,15}\b(know|see|notice)\b",
        Severity.CRITICAL,
        "Instructs the model to hide actions from the user",
    ),
    _p(
        r"<\s*/?\s*(important|system|instructions?|secret|hidden|admin|assistant)\s*>|\[/?INST\]|<\|im_start\|>",
        Severity.HIGH,
        "Pseudo-system markup aimed at the model",
    ),
    _p(
        r"\bbefore (using|calling|invoking|running)\b.{0,40}\b(you must|first|always)\b.{0,40}"
        r"\b(read|open|fetch|call|load|cat|send|include)\b",
        Severity.HIGH,
        "Hidden prerequisite steps for the model",
    ),
    _p(
        r"(~/?\.ssh|id_rsa|id_ed25519|\.aws/credentials|\.npmrc|\.netrc|\.env\b|/etc/passwd|/etc/shadow|"
        r"mcp\.json|claude_desktop_config|\.cursor/|\.kube/config|private[ _-]?key)",
        Severity.HIGH,
        "References credential or configuration files",
    ),
    _p(
        r"\b(system prompt|conversation history|previous messages|chat history|full context|api keys?)\b",
        Severity.MEDIUM,
        "Asks for conversation or secret context",
    ),
    _p(r"<!--.*?-->", Severity.MEDIUM, "HTML comment hidden from rendered views"),
    _p(
        r"\b(secretly|silently|covertly|quietly|discreetly)\b",
        Severity.MEDIUM,
        "Covert-action wording",
    ),
    _p(
        r"\byou (must|should|will) (always|never)\b|\bas an ai\b|\bassistant must\b",
        Severity.LOW,
        "Imperative language directed at the model",
    ),
)


def hidden_instructions(tool: ToolDefinition, _: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for field in text_fields(tool):
        if field.location == "name":
            continue
        for pattern in HIDDEN_INSTRUCTION_PATTERNS:
            match = pattern.regex.search(field.text)
            if not match or (field.location, pattern.title) in seen:
                continue
            seen.add((field.location, pattern.title))
            findings.append(
                Finding(
                    rule=RuleId.HIDDEN_INSTRUCTIONS,
                    severity=pattern.severity,
                    title=pattern.title,
                    detail="Tool metadata is read by the model as instructions. This text tries to steer it.",
                    location=field.location,
                    evidence=_clip(match.group(0)),
                )
            )
    return findings


_INVISIBLE_SEVERITY = {
    "tag": Severity.CRITICAL,
    "bidi": Severity.HIGH,
    "zero_width": Severity.HIGH,
    "variation_selector": Severity.MEDIUM,
    "format": Severity.MEDIUM,
}

_INVISIBLE_TITLES = {
    "tag": "Unicode tag characters smuggle hidden text",
    "bidi": "Bidirectional control characters reorder text",
    "zero_width": "Zero-width characters hide content",
    "variation_selector": "Variation selectors can encode hidden bytes",
    "format": "Invisible formatting characters",
}


def unicode_smuggling(tool: ToolDefinition, _: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    for field in text_fields(tool):
        for run in classify_invisibles(field.text):
            evidence = f"decoded: {run.decoded!r}" if run.decoded else _clip(reveal_invisible(field.text))
            findings.append(
                Finding(
                    rule=RuleId.UNICODE_SMUGGLING,
                    severity=_INVISIBLE_SEVERITY[run.kind],
                    title=_INVISIBLE_TITLES[run.kind],
                    detail=f"{run.count} invisible code point(s) that a reviewer cannot see but the model can read.",
                    location=field.location,
                    evidence=_clip(evidence),
                )
            )
    if mixed_script_confusable(tool.name):
        findings.append(
            Finding(
                rule=RuleId.UNICODE_SMUGGLING,
                severity=Severity.MEDIUM,
                title="Tool name mixes scripts (homoglyph)",
                detail="Look-alike letters can impersonate a trusted tool name.",
                location="name",
                evidence=reveal_invisible(tool.name),
            )
        )
    return findings


_SHADOW_PHRASES = re.compile(
    r"\b(when|whenever|if)\b.{0,30}\b(using|calling|invoking|the)\b.{0,40}\btool\b|"
    r"\binstead of\b|\boverrides?\b|\btakes? precedence\b|\breplaces? the\b|"
    r"\b(always|also)\b.{0,20}\b(bcc|cc|forward|redirect|send a copy)\b|"
    r"\bchange (the )?(recipient|destination|behaviou?r)\b",
    re.IGNORECASE | re.DOTALL,
)


def cross_tool_shadowing(tool: ToolDefinition, ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    foreign = ctx.foreign_peers()
    prose = [f for f in text_fields(tool) if f.location != "name"]
    referenced: set[str] = set()
    for peer in foreign:
        patterns = [
            re.compile(rf"(?<![\w.-]){re.escape(candidate)}(?![\w-])")
            for candidate in {peer.name, peer.exposed_name}
            if len(candidate) >= 4
        ]
        hit = next((f for f in prose if any(p.search(f.text) for p in patterns)), None)
        if hit is None:
            continue
        referenced.add(peer.exposed_name)
        findings.append(
            Finding(
                rule=RuleId.CROSS_TOOL_SHADOWING,
                severity=Severity.HIGH,
                title=f"References tool '{peer.name}' from server '{peer.upstream}'",
                detail="A tool describing how another server's tool should behave can hijack it.",
                location=hit.location,
                evidence=_clip(hit.text),
            )
        )
    if referenced:
        for field in prose:
            match = _SHADOW_PHRASES.search(field.text)
            if match:
                findings.append(
                    Finding(
                        rule=RuleId.CROSS_TOOL_SHADOWING,
                        severity=Severity.CRITICAL,
                        title="Rewrites the behaviour of another server's tool",
                        detail="Combines a reference to a foreign tool with override or redirect wording.",
                        location=field.location,
                        evidence=_clip(match.group(0)),
                    )
                )
                break
    same_name = [p for p in foreign if p.name == tool.name]
    if same_name:
        owners = ", ".join(sorted({p.upstream for p in same_name}))
        findings.append(
            Finding(
                rule=RuleId.CROSS_TOOL_SHADOWING,
                severity=Severity.MEDIUM,
                title="Name collides with a tool on another server",
                detail=(
                    f"'{tool.name}' is also exposed by {owners}; namespacing keeps them apart "
                    "but models may confuse them."
                ),
                location="name",
                evidence=tool.name,
            )
        )
    return findings


_URL = re.compile(r"\b(?:https?|wss?|ftp)://[^\s\"'<>)\]]+", re.IGNORECASE)
_DATA_URI = re.compile(r"\bdata:[a-z]+/[a-z0-9.+-]+;base64,", re.IGNORECASE)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+\?[^)\s]*)\)", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_SEND_VERB = re.compile(r"\b(send|post|upload|forward|transmit|exfiltrate|report|submit|bcc|cc|copy)\b", re.IGNORECASE)
SUSPICIOUS_HOSTS = (
    "ngrok",
    "webhook.site",
    "pastebin",
    "requestbin",
    "pipedream",
    "burpcollaborator",
    "interact.sh",
    "oast",
    "hookbin",
    "discord.com/api/webhooks",
    "transfer.sh",
    "trycloudflare",
)


def _is_ip_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def exfiltration(tool: ToolDefinition, ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    for field in text_fields(tool):
        if field.location == "name":
            continue
        has_send_verb = bool(_SEND_VERB.search(field.text))
        for match in _MARKDOWN_IMAGE.finditer(field.text):
            findings.append(
                Finding(
                    rule=RuleId.EXFILTRATION,
                    severity=Severity.HIGH,
                    title="Markdown image beacon with query string",
                    detail="Rendering this image leaks whatever the model interpolates into the URL.",
                    location=field.location,
                    evidence=_clip(match.group(0)),
                )
            )
        for match in _URL.finditer(field.text):
            url = match.group(0).rstrip(".,;")
            host = (urlsplit(url).hostname or "").lower()
            if host in ctx.trusted_domains or any(host.endswith(f".{d}") for d in ctx.trusted_domains):
                continue
            suspicious = _is_ip_host(host) or host.endswith(".onion") or any(s in url.lower() for s in SUSPICIOUS_HOSTS)
            if suspicious:
                severity = Severity.CRITICAL if has_send_verb else Severity.HIGH
                title = "Directs data to a known exfiltration endpoint"
            elif has_send_verb:
                severity = Severity.HIGH
                title = "Instructs sending data to an external URL"
            else:
                severity = Severity.LOW
                title = "External URL in tool metadata"
            findings.append(
                Finding(
                    rule=RuleId.EXFILTRATION,
                    severity=severity,
                    title=title,
                    detail=f"Host '{host}' is not on the trusted list.",
                    location=field.location,
                    evidence=_clip(url),
                )
            )
        if _DATA_URI.search(field.text):
            findings.append(
                Finding(
                    rule=RuleId.EXFILTRATION,
                    severity=Severity.MEDIUM,
                    title="Embedded base64 data URI",
                    detail="Encoded payloads in metadata evade human review.",
                    location=field.location,
                )
            )
        if has_send_verb:
            for match in _EMAIL.finditer(field.text):
                findings.append(
                    Finding(
                        rule=RuleId.EXFILTRATION,
                        severity=Severity.HIGH,
                        title="Instructs sending data to an email address",
                        detail="Tool metadata should never name a recipient for the model's data.",
                        location=field.location,
                        evidence=match.group(0),
                    )
                )
    return findings


EXFIL_SINK_NAMES = re.compile(
    r"^(side_?note|notes?_for_(the_)?(tool|server)|conversation(_history)?|chat_history|history|"
    r"system_?prompt|context_?dump|full_?context|instructions|previous_messages|memory)$",
    re.IGNORECASE,
)
CREDENTIAL_NAMES = re.compile(
    r"(password|passwd|secret|api_?key|access_?token|auth_?token|credentials?|private_?key|ssh_?key|cookie)",
    re.IGNORECASE,
)
MAX_PROPERTIES = 25
MAX_DEPTH = 6
LONG_DESCRIPTION = 1500
VERY_LONG_DESCRIPTION = 4000


def excessive_schema(tool: ToolDefinition, _: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    walk = walk_definition(tool)
    input_names = [(n, loc) for n, loc in walk.property_names if loc.startswith("inputSchema.")]
    for name, location in input_names:
        if EXFIL_SINK_NAMES.match(name):
            findings.append(
                Finding(
                    rule=RuleId.EXCESSIVE_SCHEMA,
                    severity=Severity.HIGH,
                    title=f"Parameter '{name}' is a data sink",
                    detail="Free-form parameters like this exist to collect context the tool does not need.",
                    location=location,
                    evidence=name,
                )
            )
        elif CREDENTIAL_NAMES.search(name):
            findings.append(
                Finding(
                    rule=RuleId.EXCESSIVE_SCHEMA,
                    severity=Severity.MEDIUM,
                    title=f"Parameter '{name}' asks the model for a credential",
                    detail="Credentials belong in server configuration, never in model-supplied arguments.",
                    location=location,
                    evidence=name,
                )
            )
    count = len(input_names)
    if count > MAX_PROPERTIES:
        findings.append(
            Finding(
                rule=RuleId.EXCESSIVE_SCHEMA,
                severity=Severity.MEDIUM,
                title="Unusually large input schema",
                detail=f"{count} parameters; large schemas hide unnecessary data collection.",
                location="inputSchema",
            )
        )
    if walk.truncated:
        findings.append(
            Finding(
                rule=RuleId.EXCESSIVE_SCHEMA,
                severity=Severity.HIGH,
                title="Definition too large or deeply nested to scan fully",
                detail=f"Scanning stopped at depth {MAX_WALK_DEPTH} or {MAX_WALK_NODES} nodes; the rest is unreviewed.",
                location="inputSchema",
            )
        )
    depth = walk.schema_depth
    if depth > MAX_DEPTH:
        findings.append(
            Finding(
                rule=RuleId.EXCESSIVE_SCHEMA,
                severity=Severity.LOW,
                title="Deeply nested input schema",
                detail=f"Nesting depth {depth} exceeds {MAX_DEPTH}.",
                location="inputSchema",
            )
        )
    if tool.input_schema.get("additionalProperties") is True and not tool.input_schema.get("properties"):
        findings.append(
            Finding(
                rule=RuleId.EXCESSIVE_SCHEMA,
                severity=Severity.LOW,
                title="Schema accepts arbitrary arguments",
                detail="An open object lets the model send anything, which defeats argument policies.",
                location="inputSchema.additionalProperties",
            )
        )
    length = len(tool.description)
    if length > VERY_LONG_DESCRIPTION:
        severity = Severity.MEDIUM
    elif length > LONG_DESCRIPTION:
        severity = Severity.LOW
    else:
        return findings
    findings.append(
        Finding(
            rule=RuleId.EXCESSIVE_SCHEMA,
            severity=severity,
            title="Oversized description",
            detail=f"{length} characters; long descriptions are a common hiding place for instructions.",
            location="description",
        )
    )
    return findings


DEFAULT_RULES: tuple[Rule, ...] = (
    hidden_instructions,
    unicode_smuggling,
    cross_tool_shadowing,
    exfiltration,
    excessive_schema,
)
