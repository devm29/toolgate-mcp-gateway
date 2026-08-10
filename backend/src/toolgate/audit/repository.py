from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolgate.audit.models import AuditEvent
from toolgate.audit.schemas import AuditFilters, Decision

BLOCKED = [d.value for d in Decision if d.blocked]
# Calls that got past the gateway and then failed (tool or upstream errors). Blocked calls also carry
# is_error, so they are excluded here; otherwise the overview would count each one twice.
_FAILED = AuditEvent.is_error.is_(True) & AuditEvent.decision.notin_(BLOCKED)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        self._session.add(event)

    def _filtered(self, filters: AuditFilters) -> Select[AuditEvent]:
        stmt = select(AuditEvent)
        if filters.decision is not None:
            stmt = stmt.where(AuditEvent.decision == filters.decision.value)
        if filters.tool:
            stmt = stmt.where(AuditEvent.tool_name == filters.tool)
        if filters.principal:
            stmt = stmt.where(AuditEvent.principal == filters.principal)
        if filters.upstream:
            stmt = stmt.where(AuditEvent.upstream == filters.upstream)
        return stmt

    async def page(self, filters: AuditFilters, *, before_id: int | None, limit: int) -> Sequence[AuditEvent]:
        stmt = self._filtered(filters)
        if before_id is not None:
            stmt = stmt.where(AuditEvent.id < before_id)
        return (await self._session.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit))).all()

    async def after(self, after_id: int, limit: int) -> Sequence[AuditEvent]:
        stmt = select(AuditEvent).where(AuditEvent.id > after_id).order_by(AuditEvent.id).limit(limit)
        return (await self._session.scalars(stmt)).all()

    async def decision_counts(self, since: datetime) -> dict[str, int]:
        stmt = (
            select(AuditEvent.decision, func.count())
            .where(AuditEvent.occurred_at >= since)
            .group_by(AuditEvent.decision)
        )
        return dict((await self._session.execute(stmt)).all())

    async def error_count(self, since: datetime) -> int:
        stmt = select(func.count()).where(AuditEvent.occurred_at >= since, _FAILED)
        return int(await self._session.scalar(stmt) or 0)

    async def p95_latency(self, since: datetime) -> float:
        stmt = select(func.percentile_cont(0.95).within_group(AuditEvent.latency_ms)).where(
            AuditEvent.occurred_at >= since, AuditEvent.decision == Decision.ALLOWED.value
        )
        return float(await self._session.scalar(stmt) or 0.0)

    async def hourly(self, since: datetime) -> Sequence[tuple[datetime, int, int, int]]:
        hour = func.date_trunc("hour", AuditEvent.occurred_at)
        stmt = (
            select(
                hour,
                func.count().filter(AuditEvent.decision == Decision.ALLOWED.value),
                func.count().filter(AuditEvent.decision.in_(BLOCKED)),
                func.count().filter(_FAILED),
            )
            .where(AuditEvent.occurred_at >= since)
            .group_by(hour)
            .order_by(hour)
        )
        return (await self._session.execute(stmt)).all()

    async def top_tools(self, since: datetime, limit: int = 6) -> Sequence[tuple[str, int, int]]:
        blocked = func.sum(case((AuditEvent.decision.in_(BLOCKED), 1), else_=0))
        stmt = (
            select(AuditEvent.tool_name, func.count(), blocked)
            .where(AuditEvent.occurred_at >= since)
            .group_by(AuditEvent.tool_name)
            .order_by(func.count().desc())
            .limit(limit)
        )
        return [(name, int(calls), int(b or 0)) for name, calls, b in (await self._session.execute(stmt))]
