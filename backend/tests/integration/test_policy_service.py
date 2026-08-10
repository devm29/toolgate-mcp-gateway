from __future__ import annotations

import asyncio

import pytest

from toolgate.errors import ConflictError
from toolgate.policy.schemas import PolicyCreate, PolicyRule, PolicyUpdate

pytestmark = pytest.mark.asyncio


async def test_concurrent_updates_with_same_version_conflict(container) -> None:
    created = await container.policies.create(
        PolicyCreate(name="p", rules=[PolicyRule(id="a", effect="allow", tools=["weather__*"])])
    )

    async def edit(tools: str) -> object:
        update = PolicyUpdate(
            name="p",
            rules=[PolicyRule(id="a", effect="allow", tools=[tools])],
            expected_version=created.version,
        )
        try:
            return await container.policies.update(created.id, update)
        except ConflictError as exc:
            return exc

    outcomes = await asyncio.gather(edit("github__*"), edit("crm__*"))
    conflicts = [o for o in outcomes if isinstance(o, ConflictError)]
    assert len(conflicts) == 1
    assert (await container.policies.get(created.id)).version == created.version + 1
