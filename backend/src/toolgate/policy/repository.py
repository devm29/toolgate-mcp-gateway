from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolgate.policy.models import PolicyRecord


class PolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> Sequence[PolicyRecord]:
        result = await self._session.scalars(select(PolicyRecord).order_by(PolicyRecord.name))
        return result.all()

    async def get(self, policy_id: uuid.UUID, *, for_update: bool = False) -> PolicyRecord | None:
        stmt = select(PolicyRecord).where(PolicyRecord.id == policy_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self._session.scalar(stmt)

    async def get_by_name(self, name: str) -> PolicyRecord | None:
        return await self._session.scalar(select(PolicyRecord).where(PolicyRecord.name == name))

    def add(self, record: PolicyRecord) -> None:
        self._session.add(record)

    async def delete(self, record: PolicyRecord) -> None:
        await self._session.delete(record)
