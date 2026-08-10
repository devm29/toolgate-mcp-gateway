from __future__ import annotations

import asyncio
import time
import uuid

from toolgate.common.principal import Principal
from toolgate.db import SessionFactory, transaction
from toolgate.errors import ConflictError, NotFoundError
from toolgate.policy.evaluator import Decision, PolicySet
from toolgate.policy.models import PolicyRecord
from toolgate.policy.repository import PolicyRepository
from toolgate.policy.schemas import Policy, PolicyCreate, PolicyUpdate, SimulationRequest


class PolicyService:
    """CRUD plus a compiled PolicySet cache. Writes invalidate locally; the TTL bounds staleness across replicas."""

    def __init__(self, sessions: SessionFactory, *, cache_ttl_seconds: float = 2.0) -> None:
        self._sessions = sessions
        self._ttl = cache_ttl_seconds
        self._cached: PolicySet | None = None
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def list(self) -> list[Policy]:
        async with self._sessions() as session:
            return [Policy.model_validate(r) for r in await PolicyRepository(session).list()]

    async def get(self, policy_id: uuid.UUID) -> Policy:
        async with self._sessions() as session:
            record = await PolicyRepository(session).get(policy_id)
            if record is None:
                raise NotFoundError("Policy not found")
            return Policy.model_validate(record)

    async def create(self, payload: PolicyCreate) -> Policy:
        async with transaction(self._sessions) as session:
            repo = PolicyRepository(session)
            if await repo.get_by_name(payload.name):
                raise ConflictError(f"A policy named '{payload.name}' already exists")
            record = PolicyRecord(
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                rules=[r.model_dump(mode="json") for r in payload.rules],
                version=1,
            )
            repo.add(record)
            await session.flush()
            policy = Policy.model_validate(record)
        self.invalidate()
        return policy

    async def update(self, policy_id: uuid.UUID, payload: PolicyUpdate) -> Policy:
        async with transaction(self._sessions) as session:
            repo = PolicyRepository(session)
            # The row lock serializes concurrent editors so the version check below cannot race.
            record = await repo.get(policy_id, for_update=True)
            if record is None:
                raise NotFoundError("Policy not found")
            if payload.expected_version is not None and payload.expected_version != record.version:
                raise ConflictError(
                    "Policy was modified by someone else; reload and try again",
                    extra={"current_version": record.version},
                )
            clash = await repo.get_by_name(payload.name)
            if clash is not None and clash.id != record.id:
                raise ConflictError(f"A policy named '{payload.name}' already exists")
            record.name = payload.name
            record.description = payload.description
            record.enabled = payload.enabled
            record.rules = [r.model_dump(mode="json") for r in payload.rules]
            record.version += 1
            await session.flush()
            await session.refresh(record)
            policy = Policy.model_validate(record)
        self.invalidate()
        return policy

    async def delete(self, policy_id: uuid.UUID) -> None:
        async with transaction(self._sessions) as session:
            repo = PolicyRepository(session)
            record = await repo.get(policy_id)
            if record is None:
                raise NotFoundError("Policy not found")
            await repo.delete(record)
        self.invalidate()

    def invalidate(self) -> None:
        self._cached = None

    async def policy_set(self) -> PolicySet:
        cached = self._cached
        if cached is not None and time.monotonic() - self._loaded_at < self._ttl:
            return cached
        async with self._lock:
            if self._cached is not None and time.monotonic() - self._loaded_at < self._ttl:
                return self._cached
            self._cached = PolicySet(await self.list())
            self._loaded_at = time.monotonic()
            return self._cached

    async def simulate(self, request: SimulationRequest) -> Decision:
        principal = Principal(subject=request.principal, client_id=request.client_id)
        policy_set = await self.policy_set()
        return policy_set.evaluate(principal.identities, request.tool, request.arguments)
