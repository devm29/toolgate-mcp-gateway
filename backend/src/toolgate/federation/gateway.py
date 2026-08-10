from __future__ import annotations

import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import mcp_types as types
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp.shared.exceptions import MCPError
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from toolgate.audit.schemas import AuditEventCreate, Decision
from toolgate.audit.service import AuditService
from toolgate.auth import scopes
from toolgate.common.principal import Principal
from toolgate.common.schema_errors import describe_error
from toolgate.common.tool_definition import ToolDefinition
from toolgate.errors import UpstreamUnavailableError
from toolgate.federation.pool import SessionPool
from toolgate.logging import get_logger
from toolgate.policy.ratelimit import RateLimiter
from toolgate.policy.service import PolicyService
from toolgate.registry.models import Tool, ToolStatus
from toolgate.registry.service import RegistryService
from toolgate.scanner.output import scan_result

log = get_logger(__name__)

DECISION_META_KEY = "dev.toolgate/decision"
OUTPUT_FINDINGS_META_KEY = "dev.toolgate/output-findings"
VALIDATOR_CACHE_SIZE = 512


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    reason: str
    tool: Tool | None = None
    detail: list[str] | None = None


def blocked_result(verdict: Verdict) -> types.CallToolResult:
    lines = [f"Toolgate blocked this call ({verdict.decision.value}): {verdict.reason}"]
    lines.extend(f"- {item}" for item in verdict.detail or [])
    return types.CallToolResult.model_validate(
        {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": True,
            "_meta": {DECISION_META_KEY: verdict.decision.value},
        }
    )


class GatewayService:
    """The tools/call pipeline: identity -> lookup -> pin check -> schema -> policy -> rate limit -> upstream."""

    def __init__(
        self,
        *,
        registry: RegistryService,
        policies: PolicyService,
        limiter: RateLimiter,
        pool: SessionPool,
        audit: AuditService,
        tracer: Tracer,
        call_timeout: float,
    ) -> None:
        self._registry = registry
        self._policies = policies
        self._limiter = limiter
        self._pool = pool
        self._audit = audit
        self._tracer = tracer
        self._timeout = call_timeout
        self._validators: OrderedDict[str, Draft202012Validator] = OrderedDict()

    async def list_tools(self, principal: Principal) -> list[types.Tool]:
        if not principal.has_scope(scopes.TOOLS_LIST):
            raise MCPError(types.INVALID_REQUEST, f"Token lacks the {scopes.TOOLS_LIST} scope")
        policy_set = await self._policies.policy_set()
        visible: list[types.Tool] = []
        for tool in await self._registry.servable_tools():
            if not policy_set.evaluate(principal.identities, tool.exposed_name, None).allowed:
                continue
            # Clients only ever see the pinned definition, never whatever the upstream says today.
            pinned = ToolDefinition.model_validate(tool.approved_definition)
            visible.append(pinned.to_mcp(tool.exposed_name))
        return visible

    async def call_tool(
        self, principal: Principal, name: str, arguments: dict[str, Any] | None, *, rpc_id: str | int | None = None
    ) -> types.CallToolResult:
        request_id = uuid.uuid4().hex
        args = dict(arguments or {})
        started = time.perf_counter()
        attributes: dict[str, str | int] = {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": name,
            "gen_ai.tool.call.id": request_id,
            "gen_ai.tool.type": "extension",
            "mcp.method.name": "tools/call",
            "toolgate.principal": principal.subject,
        }
        if rpc_id is not None:
            attributes["jsonrpc.request.id"] = str(rpc_id)
        with self._tracer.start_as_current_span(
            f"execute_tool {name}", kind=SpanKind.INTERNAL, attributes=attributes
        ) as span:
            verdict = await self._authorize(principal, name, args)
            tool = verdict.tool
            if tool is not None:
                span.set_attribute("toolgate.upstream", tool.upstream.name)
                span.set_attribute("toolgate.upstream_tool", tool.upstream_tool_name)

            result: types.CallToolResult
            is_error = False
            output_flags: list[str] = []
            if verdict.decision is Decision.ALLOWED and tool is not None:
                result, verdict = await self._forward(tool, args, verdict)
                is_error = bool(result.is_error)
                result, output_flags = _flag_output(result)
                if output_flags:
                    span.set_attribute("toolgate.output_findings", len(output_flags))
            else:
                result = blocked_result(verdict)
                is_error = True

            latency_ms = (time.perf_counter() - started) * 1000
            span.set_attribute("toolgate.decision", verdict.decision.value)
            if verdict.decision is not Decision.ALLOWED:
                span.set_attribute("error.type", f"toolgate.{verdict.decision.value}")
            if verdict.decision is Decision.UPSTREAM_ERROR:
                span.set_status(Status(StatusCode.ERROR, verdict.reason))
            elif is_error:
                span.set_attribute("error.type", "tool_error")

            context = span.get_span_context()
            await self._audit.record(
                AuditEventCreate(
                    request_id=request_id,
                    principal=principal.subject,
                    client_id=principal.client_id,
                    tool_name=name,
                    upstream=tool.upstream.name if tool else None,
                    upstream_tool=tool.upstream_tool_name if tool else None,
                    decision=verdict.decision,
                    reason=_audit_reason(verdict, output_flags),
                    arguments=args,
                    latency_ms=round(latency_ms, 2),
                    is_error=is_error,
                    trace_id=f"{context.trace_id:032x}" if context.is_valid else None,
                    span_id=f"{context.span_id:016x}" if context.is_valid else None,
                )
            )
        if verdict.decision is Decision.UNKNOWN_TOOL:
            raise MCPError(types.INVALID_PARAMS, f"Unknown tool: {name}")
        return result

    async def _authorize(self, principal: Principal, name: str, args: dict[str, Any]) -> Verdict:
        if not principal.has_scope(scopes.TOOLS_CALL):
            return Verdict(Decision.DENIED, f"Token lacks the {scopes.TOOLS_CALL} scope")
        tool = await self._registry.find_exposed(name)
        if tool is None or tool.removed_at is not None or not tool.upstream.enabled:
            return Verdict(Decision.UNKNOWN_TOOL, "No such tool is exposed by this gateway")
        if tool.status is ToolStatus.QUARANTINED or (
            tool.approved_hash is not None and tool.approved_hash != tool.current_hash
        ):
            return Verdict(
                Decision.QUARANTINED,
                "The upstream changed this tool's definition after it was approved; an admin must review the change",
                tool,
            )
        if not tool.is_servable:
            label = "rejected by an administrator" if tool.status is ToolStatus.REJECTED else "awaiting approval"
            return Verdict(Decision.QUARANTINED, f"Tool is {label}", tool)

        schema_errors = self._schema_errors(tool, args)
        if schema_errors:
            return Verdict(Decision.DENIED, "Arguments do not match the approved input schema", tool, schema_errors)

        policy_set = await self._policies.policy_set()
        decision = policy_set.evaluate(principal.identities, name, args)
        if not decision.allowed:
            return Verdict(Decision.DENIED, decision.reason, tool, decision.violations or None)
        for binding in decision.rate_limits:
            outcome = await self._limiter.consume(binding.key, binding.limit)
            if not outcome.allowed:
                return Verdict(
                    Decision.RATE_LIMITED,
                    f"Rate limit {binding.rule.policy_name}/{binding.rule.rule_id} exceeded; "
                    f"retry in {outcome.retry_after_seconds:.1f}s",
                    tool,
                )
        return Verdict(Decision.ALLOWED, decision.reason, tool)

    async def _forward(
        self, tool: Tool, args: dict[str, Any], verdict: Verdict
    ) -> tuple[types.CallToolResult, Verdict]:
        try:
            connection = self._pool.require(tool.upstream_id, tool.upstream.name)
            result = await connection.call_tool(tool.upstream_tool_name, args, timeout=self._timeout)
        except UpstreamUnavailableError as exc:
            failed = Verdict(Decision.UPSTREAM_ERROR, exc.detail, tool)
        except TimeoutError:
            failed = Verdict(Decision.UPSTREAM_ERROR, f"Upstream did not answer within {self._timeout:.0f}s", tool)
        except MCPError as exc:
            failed = Verdict(
                Decision.UPSTREAM_ERROR, f"Upstream returned error {exc.error.code}: {exc.error.message}", tool
            )
        except Exception as exc:
            log.exception("upstream_call_failed", tool=tool.exposed_name)
            failed = Verdict(Decision.UPSTREAM_ERROR, f"Upstream call failed: {type(exc).__name__}", tool)
        else:
            return result, verdict
        return blocked_result(failed), failed

    def _validator(self, tool: Tool) -> Draft202012Validator:
        key = tool.approved_hash or ""
        cached = self._validators.get(key)
        if cached is not None:
            self._validators.move_to_end(key)
            return cached
        pinned = ToolDefinition.model_validate(tool.approved_definition)
        Draft202012Validator.check_schema(pinned.input_schema)
        validator = Draft202012Validator(pinned.input_schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
        self._validators[key] = validator
        if len(self._validators) > VALIDATOR_CACHE_SIZE:
            self._validators.popitem(last=False)
        return validator

    def _schema_errors(self, tool: Tool, args: dict[str, Any]) -> list[str]:
        # Fail closed: a pinned schema the gateway cannot evaluate must never wave arguments through.
        try:
            return [describe_error(err) for err in self._validator(tool).iter_errors(args)][:5]
        except SchemaError as exc:
            return [f"the approved input schema is invalid ({exc.validator}); re-approve the tool"]
        except re.error:
            return ["the approved input schema contains an invalid pattern; re-approve the tool"]


def _audit_reason(verdict: Verdict, output_flags: list[str]) -> str:
    reason = verdict.reason if not verdict.detail else f"{verdict.reason}: {'; '.join(verdict.detail)}"
    if output_flags:
        reason = f"{reason} [output flagged: {'; '.join(output_flags)}]"
    return reason


def _flag_output(result: types.CallToolResult) -> tuple[types.CallToolResult, list[str]]:
    """Tool output goes straight into the model's context, so it gets the same injection checks as metadata.

    The result is still delivered (blocking would break legitimate tools that quote untrusted text), but the
    findings are attached in _meta for agent hosts to act on and recorded in the audit log.
    """
    texts = [block.text for block in result.content if isinstance(block, types.TextContent)]
    flags = scan_result(texts)
    if not flags:
        return result, []
    meta = dict(result.meta or {})
    meta[OUTPUT_FINDINGS_META_KEY] = flags
    return result.model_copy(update={"meta": meta}), flags
