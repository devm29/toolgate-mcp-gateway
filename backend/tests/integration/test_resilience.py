from __future__ import annotations

import os
import signal
import subprocess

import pytest
from fixtures.servers import crm

from tests.integration.helpers import free_port, register_and_sync, serve, wait_until
from toolgate.audit.schemas import Decision
from toolgate.common.principal import Principal
from toolgate.policy.schemas import PolicyCreate, PolicyRule
from toolgate.registry.models import Transport, UpstreamStatus
from toolgate.registry.schemas import UpstreamCreate

pytestmark = pytest.mark.asyncio

ALICE = Principal(subject="user:alice", scopes=frozenset({"mcp:tools.list", "mcp:tools.call"}))


async def _allow_all(container) -> None:
    await container.policies.create(
        PolicyCreate(name="allow-all", rules=[PolicyRule(id="all", effect="allow", tools=["*"])])
    )


async def _approve(container, exposed: str) -> None:
    tool = await container.registry.find_exposed(exposed)
    await container.registry.approve(tool.id, tool.current_hash, "user:alice")


def _child_pids(module: str) -> list[int]:
    out = subprocess.run(
        ["pgrep", "-P", str(os.getpid()), "-f", module], capture_output=True, text=True, check=False
    ).stdout
    return [int(pid) for pid in out.split()]


async def test_dead_stdio_upstream_is_reconnected(container) -> None:
    upstream, _ = await register_and_sync(container, "weather", "weather")
    await _approve(container, "weather__get_forecast")
    await _allow_all(container)
    assert not (await container.gateway.call_tool(ALICE, "weather__get_forecast", {"city": "Oslo"})).is_error

    pids = _child_pids("fixtures.servers.weather")
    assert pids, "fixture process not found"
    for pid in pids:
        os.kill(pid, signal.SIGKILL)

    # The first call after the crash fails cleanly and is audited as an upstream error...
    failed = await container.gateway.call_tool(ALICE, "weather__get_forecast", {"city": "Oslo"})
    assert failed.is_error
    page = await container.audit.page(_filters(), cursor=None, limit=1)
    assert page.items[0].decision is Decision.UPSTREAM_ERROR

    # ...and the supervisor brings up a fresh process instead of returning "Connection closed" forever.
    connection = container.pool.get(upstream.id)

    async def recovered() -> bool:
        if not connection.connected:
            return False
        result = await container.gateway.call_tool(ALICE, "weather__get_forecast", {"city": "Oslo"})
        return not result.is_error

    await wait_until(recovered, within=15, interval=0.25)
    assert set(_child_pids("fixtures.servers.weather")).isdisjoint(pids)


async def test_health_check_notices_silent_death(container, settings) -> None:
    del container  # resets the schema; this test needs its own container with a fast health check
    from toolgate.container import build_container

    fast = settings.model_copy(update={"upstream_health_interval_seconds": 0.2})
    local = await build_container(fast)
    try:
        upstream, _ = await register_and_sync(local, "weather", "weather")
        connection = local.pool.get(upstream.id)
        for pid in _child_pids("fixtures.servers.weather"):
            os.kill(pid, signal.SIGKILL)

        async def marked_down() -> bool:
            stored = await local.registry.get_upstream(upstream.id)
            return stored.status is UpstreamStatus.DEGRADED or not connection.connected

        await wait_until(marked_down, within=10)
        await wait_until(lambda: connection.connected, within=15)
    finally:
        await local.close()


async def test_streamable_http_upstream_federates(container) -> None:
    fixture = crm.server()
    port = free_port()
    async with serve(fixture.http_app(path="/mcp"), port) as base:
        upstream = await container.registry.create_upstream(
            UpstreamCreate(
                name="crm",
                display_name="CRM",
                transport=Transport.STREAMABLE_HTTP,
                url=f"{base}/mcp",  # type: ignore[arg-type]
                headers={"X-Upstream-Key": "configured-by-operator"},
            )
        )
        await container.pool.ensure(await container.registry.get_upstream(upstream.id))
        result = await container.sync.sync(upstream.id)
        assert set(result.new) == {"crm__lookup_customer", "crm__create_ticket"}
        await _approve(container, "crm__lookup_customer")
        await _allow_all(container)
        call = await container.gateway.call_tool(ALICE, "crm__lookup_customer", {"email": "dana@northwind.io"})
        assert not call.is_error
        assert "Dana" in call.content[0].text
        await container.pool.remove(upstream.id)


def _filters():
    from toolgate.audit.schemas import AuditFilters

    return AuditFilters()
