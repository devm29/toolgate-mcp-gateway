from __future__ import annotations

from datetime import UTC, datetime, timedelta

from toolgate.audit.broadcaster import AuditBroadcaster
from toolgate.audit.models import AuditEvent
from toolgate.audit.redaction import redact_arguments, redact_text
from toolgate.audit.repository import AuditRepository
from toolgate.audit.schemas import (
    AuditEventCreate,
    AuditEventOut,
    AuditFilters,
    AuditStats,
    Decision,
    HourlyBucket,
    ToolUsage,
)
from toolgate.common.pagination import CursorPage
from toolgate.db import SessionFactory, transaction
from toolgate.logging import get_logger

log = get_logger(__name__)


class AuditService:
    def __init__(self, sessions: SessionFactory, broadcaster: AuditBroadcaster) -> None:
        self._sessions = sessions
        self._broadcaster = broadcaster

    async def record(self, payload: AuditEventCreate) -> AuditEventOut:
        values = payload.model_dump(exclude_none=True)
        values["arguments"] = redact_arguments(payload.arguments)
        if payload.reason:
            values["reason"] = redact_text(payload.reason, payload.arguments)
        async with transaction(self._sessions) as session:
            event = AuditEvent(**values)
            AuditRepository(session).add(event)
            await session.flush()
            out = AuditEventOut.model_validate(event)
        try:
            await self._broadcaster.publish(out)
        except Exception:
            # The durable record is already committed; a missed live update must never fail the call.
            log.exception("audit_publish_failed", audit_id=out.id)
        return out

    async def page(self, filters: AuditFilters, *, cursor: str | None, limit: int) -> CursorPage[AuditEventOut]:
        before_id = int(cursor) if cursor and cursor.isdigit() else None
        async with self._sessions() as session:
            rows = await AuditRepository(session).page(filters, before_id=before_id, limit=limit + 1)
        items = [AuditEventOut.model_validate(r) for r in rows[:limit]]
        next_cursor = str(items[-1].id) if len(rows) > limit and items else None
        return CursorPage(items=items, next_cursor=next_cursor)

    async def replay_after(self, after_id: int, limit: int = 500) -> list[AuditEventOut]:
        async with self._sessions() as session:
            return [AuditEventOut.model_validate(r) for r in await AuditRepository(session).after(after_id, limit)]

    async def stats(self, *, hours: int = 24, now: datetime | None = None) -> AuditStats:
        current = now or datetime.now(UTC)
        # The window is the current hour plus the hours-1 before it, so the hourly buckets add up to the totals.
        start = current.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
        async with self._sessions() as session:
            repo = AuditRepository(session)
            counts = await repo.decision_counts(start)
            errors = await repo.error_count(start)
            p95 = await repo.p95_latency(start)
            hourly_rows = await repo.hourly(start)
            top = await repo.top_tools(start)
        by_decision = {d: counts.get(d.value, 0) for d in Decision}
        seen = {row[0].astimezone(UTC): row for row in hourly_rows}
        hourly: list[HourlyBucket] = []
        for offset in range(hours):
            hour = start + timedelta(hours=offset)
            row = seen.get(hour)
            hourly.append(
                HourlyBucket(hour=hour, allowed=row[1], blocked=row[2], errors=row[3])
                if row
                else HourlyBucket(hour=hour)
            )
        total = sum(by_decision.values())
        blocked = sum(v for d, v in by_decision.items() if d.blocked)
        return AuditStats(
            window_hours=hours,
            total=total,
            allowed=by_decision[Decision.ALLOWED],
            blocked=blocked,
            errors=errors,
            p95_latency_ms=round(p95, 1),
            by_decision=by_decision,
            hourly=hourly,
            top_tools=[ToolUsage(tool_name=n, calls=c, blocked=b) for n, c, b in top],
        )
