from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from toolgate.registry.models import Tool, ToolChange, ToolPin, ToolStatus, Upstream
from toolgate.registry.schemas import ToolCounts, ToolFilters
from toolgate.scanner.models import RiskLevel


class RegistryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_upstreams(self) -> Sequence[Upstream]:
        return (await self._session.scalars(select(Upstream).order_by(Upstream.name))).all()

    async def get_upstream(self, upstream_id: uuid.UUID, *, for_update: bool = False) -> Upstream | None:
        stmt = select(Upstream).where(Upstream.id == upstream_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self._session.scalar(stmt)

    async def get_upstream_by_name(self, name: str) -> Upstream | None:
        return await self._session.scalar(select(Upstream).where(Upstream.name == name))

    def add(self, obj: Upstream | Tool | ToolPin | ToolChange) -> None:
        self._session.add(obj)

    async def flush(self) -> None:
        await self._session.flush()

    async def delete(self, obj: Upstream) -> None:
        await self._session.delete(obj)

    async def tool_counts(self) -> dict[uuid.UUID, ToolCounts]:
        stmt = (
            select(Tool.upstream_id, Tool.status, func.count())
            .where(Tool.removed_at.is_(None))
            .group_by(Tool.upstream_id, Tool.status)
        )
        counts: dict[uuid.UUID, ToolCounts] = {}
        for upstream_id, status, count in await self._session.execute(stmt):
            bucket = counts.setdefault(upstream_id, ToolCounts())
            setattr(bucket, status.value, count)
            bucket.total += count
        return counts

    async def max_risk(self) -> dict[uuid.UUID, int]:
        stmt = (
            select(Tool.upstream_id, func.max(Tool.risk_score))
            .where(Tool.removed_at.is_(None))
            .group_by(Tool.upstream_id)
        )
        return {uid: int(score or 0) for uid, score in (await self._session.execute(stmt))}

    async def tools_for_upstream(self, upstream_id: uuid.UUID, *, for_update: bool = False) -> Sequence[Tool]:
        stmt = select(Tool).where(Tool.upstream_id == upstream_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.scalars(stmt)).all()

    async def peer_tools(self) -> Sequence[tuple[str, str, str]]:
        stmt = (
            select(Upstream.name, Tool.upstream_tool_name, Tool.exposed_name)
            .join(Tool.upstream)
            .where(Tool.removed_at.is_(None))
        )
        return (await self._session.execute(stmt)).all()

    async def exposed_name_owner(self, exposed_name: str) -> uuid.UUID | None:
        return await self._session.scalar(select(Tool.id).where(Tool.exposed_name == exposed_name))

    async def get_tool(self, tool_id: uuid.UUID, *, for_update: bool = False) -> Tool | None:
        stmt = select(Tool).options(selectinload(Tool.upstream)).where(Tool.id == tool_id)
        if for_update:
            stmt = stmt.with_for_update(of=Tool)
        return await self._session.scalar(stmt)

    async def get_tool_by_exposed_name(self, exposed_name: str) -> Tool | None:
        stmt = select(Tool).options(selectinload(Tool.upstream)).where(Tool.exposed_name == exposed_name)
        return await self._session.scalar(stmt)

    def _filtered(self, filters: ToolFilters) -> Select[Tool]:
        stmt = select(Tool).join(Tool.upstream).options(selectinload(Tool.upstream))
        if not filters.include_removed:
            stmt = stmt.where(Tool.removed_at.is_(None))
        if filters.status is not None:
            stmt = stmt.where(Tool.status == filters.status)
        if filters.upstream_id is not None:
            stmt = stmt.where(Tool.upstream_id == filters.upstream_id)
        if filters.risk is not None:
            stmt = stmt.where(Tool.risk_level == filters.risk.value)
        if filters.q:
            pattern = f"%{filters.q.replace('%', r'\%').replace('_', r'\_')}%"
            stmt = stmt.where(or_(Tool.exposed_name.ilike(pattern), Upstream.display_name.ilike(pattern)))
        return stmt

    async def list_tools(self, filters: ToolFilters, *, limit: int, offset: int) -> tuple[Sequence[Tool], int]:
        base = self._filtered(filters)
        total = await self._session.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
        rows = await self._session.scalars(
            base.order_by(Tool.risk_score.desc(), Tool.exposed_name).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def servable_tools(self) -> Sequence[Tool]:
        stmt = (
            select(Tool)
            .join(Tool.upstream)
            .options(selectinload(Tool.upstream))
            .where(
                and_(
                    Tool.status == ToolStatus.APPROVED,
                    Tool.removed_at.is_(None),
                    Tool.approved_hash == Tool.current_hash,
                    Upstream.enabled.is_(True),
                )
            )
            .order_by(Tool.exposed_name)
        )
        return (await self._session.scalars(stmt)).all()

    async def review_queue(self) -> Sequence[Tool]:
        stmt = (
            select(Tool)
            .options(selectinload(Tool.upstream))
            .where(Tool.status.in_([ToolStatus.PENDING, ToolStatus.QUARANTINED]), Tool.removed_at.is_(None))
            .order_by(Tool.status.desc(), Tool.status_changed_at.desc())
        )
        return (await self._session.scalars(stmt)).all()

    async def open_changes(self, tool_id: uuid.UUID) -> Sequence[ToolChange]:
        stmt = select(ToolChange).where(ToolChange.tool_id == tool_id, ToolChange.resolved_at.is_(None))
        return (await self._session.scalars(stmt)).all()

    async def latest_open_changes(self, tool_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ToolChange]:
        if not tool_ids:
            return {}
        stmt = (
            select(ToolChange)
            .where(ToolChange.tool_id.in_(tool_ids), ToolChange.resolved_at.is_(None))
            .order_by(ToolChange.detected_at)
        )
        return {change.tool_id: change for change in (await self._session.scalars(stmt)).all()}

    async def changes(self, tool_id: uuid.UUID, limit: int = 50) -> Sequence[ToolChange]:
        stmt = (
            select(ToolChange).where(ToolChange.tool_id == tool_id).order_by(ToolChange.detected_at.desc()).limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def pins(self, tool_id: uuid.UUID, limit: int = 50) -> Sequence[ToolPin]:
        stmt = select(ToolPin).where(ToolPin.tool_id == tool_id).order_by(ToolPin.created_at.desc()).limit(limit)
        return (await self._session.scalars(stmt)).all()

    async def status_counts(self) -> dict[ToolStatus, int]:
        stmt = select(Tool.status, func.count()).where(Tool.removed_at.is_(None)).group_by(Tool.status)
        return dict((await self._session.execute(stmt)).all())

    async def risk_counts(self) -> dict[RiskLevel, int]:
        stmt = select(Tool.risk_level, func.count()).where(Tool.removed_at.is_(None)).group_by(Tool.risk_level)
        return {RiskLevel(level): count for level, count in (await self._session.execute(stmt))}
