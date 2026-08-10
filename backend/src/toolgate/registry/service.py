from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from toolgate.common.pagination import Page, PageParams
from toolgate.common.tool_definition import ToolDefinition
from toolgate.db import SessionFactory, transaction, utcnow
from toolgate.errors import ConflictError, NotFoundError, UnprocessableError
from toolgate.logging import get_logger
from toolgate.registry import naming
from toolgate.registry.diff import DefinitionDiff, diff_definitions
from toolgate.registry.models import (
    ChangeKind,
    ChangeResolution,
    Tool,
    ToolChange,
    ToolPin,
    ToolStatus,
    Transport,
    Upstream,
    UpstreamStatus,
)
from toolgate.registry.repository import RegistryRepository
from toolgate.registry.schemas import (
    REDACTED,
    ApprovalItem,
    ChangeOut,
    PinOut,
    SyncResult,
    ToolDetail,
    ToolFilters,
    ToolSummary,
    UpstreamCreate,
    UpstreamOut,
    UpstreamUpdate,
)
from toolgate.scanner.context import PeerTool, ScanContext
from toolgate.scanner.models import RiskLevel, ScanReport
from toolgate.scanner.pipeline import Scanner, build_report, run_rules

log = get_logger(__name__)

SYSTEM_ACTOR = "system:auto-approve"


def summarize(tool: Tool) -> ToolSummary:
    definition = tool.approved_definition if tool.is_servable and tool.approved_definition else tool.current_definition
    findings = tool.scan_report.get("findings", []) if tool.scan_report else []
    return ToolSummary(
        id=tool.id,
        exposed_name=tool.exposed_name,
        upstream_id=tool.upstream_id,
        upstream_name=tool.upstream.name,
        upstream_tool_name=tool.upstream_tool_name,
        title=definition.get("title"),
        description=str(definition.get("description", "")),
        status=tool.status,
        risk_score=tool.risk_score,
        risk_level=RiskLevel(tool.risk_level),
        finding_count=len(findings),
        has_drift=tool.approved_hash is not None and tool.approved_hash != tool.current_hash,
        removed=tool.removed_at is not None,
        first_seen_at=tool.first_seen_at,
        last_seen_at=tool.last_seen_at,
        status_changed_at=tool.status_changed_at,
        approved_at=tool.approved_at,
        approved_by=tool.approved_by,
    )


def _scan_report(tool: Tool) -> ScanReport | None:
    if not tool.scan_report:
        return None
    try:
        return ScanReport.model_validate(tool.scan_report)
    except ValidationError:
        return None


def _check_input_schema(definition: dict[str, Any]) -> None:
    """A pin must hold a schema the gateway can enforce; otherwise argument checks would have nothing to run."""
    schema = definition.get("input_schema")
    if not isinstance(schema, dict):
        raise UnprocessableError("The tool's input schema is not a JSON object")
    try:
        # The metaschema checks "pattern" values with the regex format, so bad regexes surface here too.
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise UnprocessableError(f"The tool's input schema is invalid and cannot be enforced: {exc.message}") from exc


class RegistryService:
    def __init__(self, sessions: SessionFactory, scanner: Scanner, *, auto_approve_clean: bool = False) -> None:
        self._sessions = sessions
        self._scanner = scanner
        self._auto_approve_clean = auto_approve_clean

    async def list_upstreams(self) -> list[UpstreamOut]:
        async with self._sessions() as session:
            repo = RegistryRepository(session)
            counts = await repo.tool_counts()
            risk = await repo.max_risk()
            out: list[UpstreamOut] = []
            for upstream in await repo.list_upstreams():
                item = UpstreamOut.model_validate(upstream)
                if upstream.id in counts:
                    item.tool_counts = counts[upstream.id]
                item.max_risk_score = risk.get(upstream.id, 0)
                out.append(item)
            return out

    async def upstream_models(self) -> list[Upstream]:
        async with self._sessions() as session:
            return list(await RegistryRepository(session).list_upstreams())

    async def get_upstream(self, upstream_id: uuid.UUID) -> Upstream:
        async with self._sessions() as session:
            upstream = await RegistryRepository(session).get_upstream(upstream_id)
            if upstream is None:
                raise NotFoundError("Upstream server not found")
            return upstream

    async def get_upstream_out(self, upstream_id: uuid.UUID) -> UpstreamOut:
        for item in await self.list_upstreams():
            if item.id == upstream_id:
                return item
        raise NotFoundError("Upstream server not found")

    async def create_upstream(self, payload: UpstreamCreate) -> Upstream:
        async with transaction(self._sessions) as session:
            repo = RegistryRepository(session)
            if await repo.get_upstream_by_name(payload.name):
                raise ConflictError(f"An upstream named '{payload.name}' already exists")
            upstream = Upstream(
                name=payload.name,
                display_name=payload.display_name,
                description=payload.description,
                transport=payload.transport,
                command=payload.command,
                args=payload.args,
                env=payload.env,
                cwd=payload.cwd,
                url=str(payload.url) if payload.url else None,
                headers=payload.headers,
                enabled=payload.enabled,
                status=UpstreamStatus.PENDING if payload.enabled else UpstreamStatus.DISABLED,
            )
            repo.add(upstream)
            await session.flush()
            return upstream

    async def update_upstream(self, upstream_id: uuid.UUID, payload: UpstreamUpdate) -> Upstream:
        """Partial update: omitted fields keep their stored value, so toggling one flag never drops secrets."""
        changes = payload.model_dump(exclude_unset=True)
        async with transaction(self._sessions) as session:
            upstream = await RegistryRepository(session).get_upstream(upstream_id, for_update=True)
            if upstream is None:
                raise NotFoundError("Upstream server not found")
            for name in ("display_name", "description", "transport", "command", "args", "cwd", "enabled"):
                if name in changes:
                    setattr(upstream, name, getattr(payload, name))
            if "url" in changes:
                upstream.url = str(payload.url) if payload.url else None
            # The API never returns secret values, so a redacted placeholder means "keep what is stored".
            if payload.env is not None:
                upstream.env = {k: upstream.env.get(k, "") if v == REDACTED else v for k, v in payload.env.items()}
            if payload.headers is not None:
                upstream.headers = {
                    k: upstream.headers.get(k, "") if v == REDACTED else v for k, v in payload.headers.items()
                }
            if upstream.transport is Transport.STDIO and not upstream.command:
                raise UnprocessableError("stdio upstreams need a command")
            if upstream.transport is Transport.STREAMABLE_HTTP and not upstream.url:
                raise UnprocessableError("streamable_http upstreams need a url")
            if not upstream.enabled:
                upstream.status = UpstreamStatus.DISABLED
            elif upstream.status is UpstreamStatus.DISABLED:
                upstream.status = UpstreamStatus.PENDING
            await session.flush()
            return upstream

    async def delete_upstream(self, upstream_id: uuid.UUID) -> None:
        async with transaction(self._sessions) as session:
            repo = RegistryRepository(session)
            upstream = await repo.get_upstream(upstream_id)
            if upstream is None:
                raise NotFoundError("Upstream server not found")
            await repo.delete(upstream)

    async def mark_upstream(self, upstream_id: uuid.UUID, status: UpstreamStatus, error: str | None = None) -> None:
        async with transaction(self._sessions) as session:
            upstream = await RegistryRepository(session).get_upstream(upstream_id)
            if upstream is None:
                return
            if not upstream.enabled:
                status = UpstreamStatus.DISABLED
            upstream.status = status
            upstream.last_error = error

    async def _scan_context(self, upstream_name: str) -> ScanContext:
        async with self._sessions() as session:
            peers = await RegistryRepository(session).peer_tools()
        return ScanContext(
            upstream=upstream_name,
            peers=tuple(PeerTool(upstream=u, name=n, exposed_name=e) for u, n, e in peers),
        )

    async def reconcile(self, upstream_id: uuid.UUID, listed: Sequence[ToolDefinition]) -> SyncResult:
        """Fold a fresh tools/list snapshot into the registry. This is where rug pulls are caught."""
        upstream = await self.get_upstream(upstream_id)
        ctx = await self._scan_context(upstream.name)

        async with self._sessions() as session:
            known = {
                t.upstream_tool_name: t.current_hash
                for t in await RegistryRepository(session).tools_for_upstream(upstream_id)
            }
        reports: dict[str, ScanReport] = {}
        for definition in listed:
            digest = definition.sha256()
            if known.get(definition.name) != digest and digest not in reports:
                reports[digest] = await self._scanner.scan(definition, ctx)

        result = SyncResult(upstream=upstream.name, discovered=len(listed))
        now = utcnow()
        async with transaction(self._sessions) as session:
            repo = RegistryRepository(session)
            locked = await repo.get_upstream(upstream_id, for_update=True)
            if locked is None:
                raise NotFoundError("Upstream server not found")
            existing = {t.upstream_tool_name: t for t in await repo.tools_for_upstream(upstream_id, for_update=True)}
            seen: set[str] = set()
            for definition in listed:
                if definition.name in seen:
                    continue
                seen.add(definition.name)
                digest = definition.sha256()
                tool = existing.get(definition.name)
                if tool is not None and tool.current_hash == digest:
                    self._touch(tool, now)
                else:
                    # Another sync can change a tool between the pre-scan read and this lock; scan it here then.
                    report = reports.get(digest) or build_report(definition, run_rules(definition, ctx))
                    if tool is None:
                        await self._add_tool(repo, locked, definition, digest, report, now, result)
                    else:
                        await self._apply_listing(repo, tool, definition, digest, report, now, result)
                # Flush per tool so each tool row is written before its change/pin rows that reference it.
                await repo.flush()
            for name, tool in existing.items():
                if name not in seen and tool.removed_at is None:
                    tool.removed_at = now
                    tool.status_changed_at = now
                    repo.add(
                        ToolChange(
                            tool_id=tool.id,
                            kind=ChangeKind.REMOVED,
                            previous_hash=tool.current_hash,
                            new_hash=tool.current_hash,
                            previous_definition=tool.current_definition,
                            new_definition=tool.current_definition,
                            detected_at=now,
                        )
                    )
                    result.removed.append(tool.exposed_name)
            locked.last_synced_at = now
            locked.status = UpstreamStatus.CONNECTED if locked.enabled else UpstreamStatus.DISABLED
            locked.last_error = None

        if result.quarantined:
            log.warning("tools_quarantined", upstream=upstream.name, tools=result.quarantined)
        return result

    async def _add_tool(
        self,
        repo: RegistryRepository,
        upstream: Upstream,
        definition: ToolDefinition,
        digest: str,
        report: ScanReport,
        now: datetime,
        result: SyncResult,
    ) -> None:
        exposed = naming.exposed_name(upstream.name, definition.name)
        if await repo.exposed_name_owner(exposed) is not None:
            exposed = naming.disambiguated(upstream.name, definition.name)
        tool = Tool(
            id=uuid.uuid4(),
            upstream_id=upstream.id,
            upstream_tool_name=definition.name,
            exposed_name=exposed,
            status=ToolStatus.PENDING,
            current_hash=digest,
            current_definition=definition.model_dump(mode="json"),
            risk_score=report.score,
            risk_level=report.level.value,
            scan_report=report.model_dump(mode="json"),
            first_seen_at=now,
            last_seen_at=now,
            status_changed_at=now,
        )
        repo.add(tool)
        change = ToolChange(
            tool_id=tool.id,
            kind=ChangeKind.NEW,
            previous_hash=None,
            new_hash=digest,
            previous_definition=None,
            new_definition=tool.current_definition,
            detected_at=now,
        )
        repo.add(change)
        result.new.append(exposed)
        if self._auto_approve_clean and report.level is RiskLevel.NONE:
            self._pin(repo, tool, SYSTEM_ACTOR, "auto-approved: no findings", now)
            change.resolved_at = now
            change.resolution = ChangeResolution.APPROVED
            change.resolved_by = SYSTEM_ACTOR
            result.auto_approved.append(exposed)

    @staticmethod
    def _touch(tool: Tool, now: datetime) -> None:
        tool.last_seen_at = now
        if tool.removed_at is not None:
            tool.removed_at = None
            tool.status_changed_at = now

    async def _apply_listing(
        self,
        repo: RegistryRepository,
        tool: Tool,
        definition: ToolDefinition,
        digest: str,
        report: ScanReport,
        now: datetime,
        result: SyncResult,
    ) -> None:
        self._touch(tool, now)
        if digest == tool.current_hash:
            return

        previous_hash, previous_definition = tool.current_hash, tool.current_definition
        tool.current_hash = digest
        tool.current_definition = definition.model_dump(mode="json")
        tool.scan_report = report.model_dump(mode="json")
        tool.risk_score = report.score
        tool.risk_level = report.level.value
        tool.status_changed_at = now

        # Only a drift quarantine is undone by reverting; a rejection stays a rejection.
        if tool.status is ToolStatus.QUARANTINED and tool.approved_hash is not None and digest == tool.approved_hash:
            tool.status = ToolStatus.APPROVED
            await self._resolve_open(repo, tool, ChangeResolution.REVERTED, "system", now)
            result.restored.append(tool.exposed_name)
            return

        await self._resolve_open(repo, tool, ChangeResolution.SUPERSEDED, "system", now)
        repo.add(
            ToolChange(
                tool_id=tool.id,
                kind=ChangeKind.CHANGED,
                previous_hash=tool.approved_hash or previous_hash,
                new_hash=digest,
                previous_definition=tool.approved_definition or previous_definition,
                new_definition=tool.current_definition,
                detected_at=now,
            )
        )
        result.changed.append(tool.exposed_name)
        if tool.approved_hash is not None:
            tool.status = ToolStatus.QUARANTINED
            result.quarantined.append(tool.exposed_name)
        else:
            tool.status = ToolStatus.PENDING

    @staticmethod
    async def _resolve_open(
        repo: RegistryRepository, tool: Tool, resolution: ChangeResolution, actor: str, now: datetime
    ) -> list[ToolChange]:
        changes = list(await repo.open_changes(tool.id))
        for change in changes:
            change.resolved_at = now
            change.resolution = resolution
            change.resolved_by = actor
        return changes

    @staticmethod
    def _pin(repo: RegistryRepository, tool: Tool, actor: str, note: str, now: datetime) -> None:
        tool.status = ToolStatus.APPROVED
        tool.approved_hash = tool.current_hash
        tool.approved_definition = tool.current_definition
        tool.approved_by = actor
        tool.approved_at = now
        tool.status_changed_at = now
        repo.add(
            ToolPin(
                tool_id=tool.id,
                sha256=tool.current_hash,
                definition=tool.current_definition,
                approved_by=actor,
                note=note,
                created_at=now,
            )
        )

    async def approve(self, tool_id: uuid.UUID, expected_hash: str, actor: str, note: str = "") -> ToolSummary:
        now = utcnow()
        async with transaction(self._sessions) as session:
            repo = RegistryRepository(session)
            tool = await repo.get_tool(tool_id, for_update=True)
            if tool is None:
                raise NotFoundError("Tool not found")
            if tool.current_hash != expected_hash:
                raise ConflictError(
                    "The tool definition changed after you reviewed it. Review the latest version before approving.",
                    extra={"current_hash": tool.current_hash},
                )
            if tool.removed_at is not None:
                raise ConflictError("The upstream no longer lists this tool")
            _check_input_schema(tool.current_definition)
            self._pin(repo, tool, actor, note, now)
            await self._resolve_open(repo, tool, ChangeResolution.APPROVED, actor, now)
            log.info("tool_approved", tool=tool.exposed_name, actor=actor, sha256=tool.current_hash)
            return summarize(tool)

    async def reject(self, tool_id: uuid.UUID, actor: str, reason: str = "") -> ToolSummary:
        now = utcnow()
        async with transaction(self._sessions) as session:
            repo = RegistryRepository(session)
            tool = await repo.get_tool(tool_id, for_update=True)
            if tool is None:
                raise NotFoundError("Tool not found")
            tool.status = ToolStatus.REJECTED
            tool.status_changed_at = now
            # The pin history keeps what was approved before; the live pin must go, or a later
            # revert to that definition would silently bring the rejected tool back.
            tool.approved_hash = None
            tool.approved_definition = None
            await self._resolve_open(repo, tool, ChangeResolution.REJECTED, actor, now)
            log.info("tool_rejected", tool=tool.exposed_name, actor=actor, reason=reason)
            return summarize(tool)

    async def rescan(self, tool_id: uuid.UUID) -> ScanReport:
        async with self._sessions() as session:
            tool = await RegistryRepository(session).get_tool(tool_id)
            if tool is None:
                raise NotFoundError("Tool not found")
            definition = ToolDefinition.model_validate(tool.current_definition)
            upstream_name = tool.upstream.name
        report = await self._scanner.scan(definition, await self._scan_context(upstream_name))
        async with transaction(self._sessions) as session:
            locked = await RegistryRepository(session).get_tool(tool_id, for_update=True)
            if locked is not None and locked.current_hash == report.definition_hash:
                locked.scan_report = report.model_dump(mode="json")
                locked.risk_score = report.score
                locked.risk_level = report.level.value
        return report

    async def list_tools(self, filters: ToolFilters, page: PageParams) -> Page[ToolSummary]:
        async with self._sessions() as session:
            rows, total = await RegistryRepository(session).list_tools(filters, limit=page.limit, offset=page.offset)
            return Page(items=[summarize(t) for t in rows], total=total, limit=page.limit, offset=page.offset)

    async def tool_detail(self, tool_id: uuid.UUID) -> ToolDetail:
        async with self._sessions() as session:
            repo = RegistryRepository(session)
            tool = await repo.get_tool(tool_id)
            if tool is None:
                raise NotFoundError("Tool not found")
            summary = summarize(tool)
            return ToolDetail(
                **summary.model_dump(),
                current_hash=tool.current_hash,
                approved_hash=tool.approved_hash,
                current_definition=tool.current_definition,
                approved_definition=tool.approved_definition,
                scan_report=_scan_report(tool),
                pins=[PinOut.model_validate(p) for p in await repo.pins(tool.id)],
                changes=[ChangeOut.model_validate(c) for c in await repo.changes(tool.id)],
            )

    async def diff(self, tool_id: uuid.UUID) -> DefinitionDiff:
        async with self._sessions() as session:
            repo = RegistryRepository(session)
            tool = await repo.get_tool(tool_id)
            if tool is None:
                raise NotFoundError("Tool not found")
            open_change = (await repo.latest_open_changes([tool.id])).get(tool.id)
            base: dict[str, Any] | None
            base_hash: str | None
            if tool.approved_definition is not None:
                base, base_hash = tool.approved_definition, tool.approved_hash
            elif open_change is not None:
                base, base_hash = open_change.previous_definition, open_change.previous_hash
            else:
                base, base_hash = None, None
            return diff_definitions(base, tool.current_definition, base_hash=base_hash, head_hash=tool.current_hash)

    async def approval_queue(self) -> list[ApprovalItem]:
        async with self._sessions() as session:
            repo = RegistryRepository(session)
            tools = await repo.review_queue()
            changes = await repo.latest_open_changes([t.id for t in tools])
            items: list[ApprovalItem] = []
            for tool in tools:
                report = _scan_report(tool)
                change = changes.get(tool.id)
                items.append(
                    ApprovalItem(
                        tool=summarize(tool),
                        change=ChangeOut.model_validate(change) if change else None,
                        top_findings=report.findings[:3] if report else [],
                    )
                )
            return items

    async def servable_tools(self) -> list[Tool]:
        async with self._sessions() as session:
            return list(await RegistryRepository(session).servable_tools())

    async def find_exposed(self, exposed_name: str) -> Tool | None:
        async with self._sessions() as session:
            return await RegistryRepository(session).get_tool_by_exposed_name(exposed_name)

    async def status_counts(self) -> dict[ToolStatus, int]:
        async with self._sessions() as session:
            return await RegistryRepository(session).status_counts()

    async def risk_counts(self) -> dict[RiskLevel, int]:
        async with self._sessions() as session:
            return await RegistryRepository(session).risk_counts()
