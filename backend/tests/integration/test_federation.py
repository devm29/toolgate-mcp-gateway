from __future__ import annotations

import pytest

from tests.integration.helpers import detach, register_and_sync
from toolgate.common.pagination import PageParams
from toolgate.registry.models import ToolStatus
from toolgate.registry.schemas import ToolFilters

pytestmark = pytest.mark.asyncio


async def test_sync_discovers_and_namespaces_tools(container) -> None:
    _, result = await register_and_sync(container, "weather", "weather")
    assert result.discovered == 2
    assert set(result.new) == {"weather__get_forecast", "weather__get_alerts"}
    page = await container.registry.list_tools(ToolFilters(), PageParams(limit=50))
    names = {t.exposed_name for t in page.items}
    assert "weather__get_forecast" in names
    assert all(t.status is ToolStatus.PENDING for t in page.items)


async def test_name_collision_between_servers_disambiguated(container) -> None:
    await register_and_sync(container, "mailhelper", "shadowing")
    await register_and_sync(container, "mailer", "mailer")
    page = await container.registry.list_tools(ToolFilters(), PageParams(limit=100))
    send_tools = [t for t in page.items if t.upstream_tool_name == "send_email"]
    assert len(send_tools) == 2
    assert len({t.exposed_name for t in send_tools}) == 2


async def test_sync_is_idempotent(container) -> None:
    upstream, _ = await register_and_sync(container, "github", "github")
    second = await container.sync.sync(upstream.id)
    assert second.new == []
    assert second.changed == []


async def test_removed_tool_marked(container) -> None:
    upstream, _ = await register_and_sync(container, "weather", "weather")
    await detach(container, upstream.id)
    tools = await container.registry.servable_tools()
    del tools
    # Re-point to a server that lists a different tool set by swapping the module via a direct reconcile.
    from toolgate.common.tool_definition import ToolDefinition

    only_one = [
        ToolDefinition(name="get_forecast", description="Daily forecast for a city.", input_schema={"type": "object"})
    ]
    result = await container.registry.reconcile(upstream.id, only_one)
    assert "weather__get_alerts" in result.removed
