from __future__ import annotations

import hashlib
import re

SEPARATOR = "__"
MAX_TOOL_NAME = 64
# Model provider APIs accept [A-Za-z0-9_-]{1,64} for tool names, which is stricter than MCP's own rule
# (dots are legal in MCP). Exposed names use the strict set so they survive every client.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
UPSTREAM_NAME = re.compile(r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$")


def sanitize(tool_name: str) -> str:
    cleaned = _UNSAFE.sub("_", tool_name).strip("_")
    return cleaned or "tool"


def exposed_name(upstream: str, tool_name: str) -> str:
    base = f"{upstream}{SEPARATOR}{sanitize(tool_name)}"
    if len(base) <= MAX_TOOL_NAME:
        return base
    return disambiguated(upstream, tool_name)


def disambiguated(upstream: str, tool_name: str) -> str:
    """Used when sanitizing or truncation makes two different upstream tools collide on one exposed name."""
    digest = hashlib.sha256(f"{upstream}\x00{tool_name}".encode()).hexdigest()[:8]
    head = f"{upstream}{SEPARATOR}{sanitize(tool_name)}"[: MAX_TOOL_NAME - 9]
    return f"{head}_{digest}"


def split_exposed(name: str) -> tuple[str, str] | None:
    if SEPARATOR not in name:
        return None
    upstream, _, tool = name.partition(SEPARATOR)
    return upstream, tool
