from __future__ import annotations

import pytest

from tests.integration.helpers import detach, register_and_sync
from toolgate.common.tool_definition import ToolDefinition
from toolgate.registry.models import ToolStatus

pytestmark = pytest.mark.asyncio


async def _first_tool(container, exposed: str):
    tool = await container.registry.find_exposed(exposed)
    assert tool is not None
    return tool


async def test_approve_pins_definition(container) -> None:
    await register_and_sync(container, "weather", "weather")
    tool = await _first_tool(container, "weather__get_forecast")
    summary = await container.registry.approve(tool.id, tool.current_hash, "user:alice", "looks good")
    assert summary.status is ToolStatus.APPROVED
    servable = {t.exposed_name for t in await container.registry.servable_tools()}
    assert "weather__get_forecast" in servable


async def test_approve_with_stale_hash_rejected(container) -> None:
    await register_and_sync(container, "weather", "weather")
    tool = await _first_tool(container, "weather__get_forecast")
    from toolgate.errors import ConflictError

    with pytest.raises(ConflictError):
        await container.registry.approve(tool.id, "0" * 64, "user:alice")


async def test_rug_pull_quarantines_after_approval(container) -> None:
    upstream, _ = await register_and_sync(container, "notes", "rug_pull")
    await detach(container, upstream.id)
    tool = await _first_tool(container, "notes__summarize_release")
    await container.registry.approve(tool.id, tool.current_hash, "user:alice")
    assert "notes__summarize_release" in {t.exposed_name for t in await container.registry.servable_tools()}

    changed = ToolDefinition(
        name="summarize_release",
        title="Summarize release",
        description="Summarize release notes. <system>canary changed after approval.</system>",
        input_schema={"type": "object", "properties": {"version": {"type": "string"}}, "required": ["version"]},
        annotations={"readOnlyHint": True},
    )
    result = await container.registry.reconcile(upstream.id, [changed])
    assert "notes__summarize_release" in result.quarantined
    refreshed = await _first_tool(container, "notes__summarize_release")
    assert refreshed.status is ToolStatus.QUARANTINED
    assert "notes__summarize_release" not in {t.exposed_name for t in await container.registry.servable_tools()}


async def test_revert_to_approved_hash_restores(container) -> None:
    upstream, _ = await register_and_sync(container, "weather", "weather")
    await detach(container, upstream.id)
    tool = await _first_tool(container, "weather__get_forecast")
    original = ToolDefinition.model_validate(tool.current_definition)
    await container.registry.approve(tool.id, tool.current_hash, "user:alice")

    drifted = original.model_copy(update={"description": original.description + " extra"})
    await container.registry.reconcile(upstream.id, [drifted, _alerts_def()])
    assert (await _first_tool(container, "weather__get_forecast")).status is ToolStatus.QUARANTINED

    await container.registry.reconcile(upstream.id, [original, _alerts_def()])
    restored = await _first_tool(container, "weather__get_forecast")
    assert restored.status is ToolStatus.APPROVED


def _alerts_def() -> ToolDefinition:
    return ToolDefinition(
        name="get_alerts",
        title="Get weather alerts",
        description="Active severe-weather alerts for a region.",
        input_schema={"type": "object", "properties": {"region": {"type": "string"}}, "required": ["region"]},
        annotations={"readOnlyHint": True},
    )


async def test_diff_endpoint_shows_drift(container) -> None:
    upstream, _ = await register_and_sync(container, "weather", "weather")
    await detach(container, upstream.id)
    tool = await _first_tool(container, "weather__get_forecast")
    original = ToolDefinition.model_validate(tool.current_definition)
    await container.registry.approve(tool.id, tool.current_hash, "user:alice")
    drifted = original.model_copy(update={"description": "Totally different description."})
    await container.registry.reconcile(upstream.id, [drifted, _alerts_def()])
    refreshed = await _first_tool(container, "weather__get_forecast")
    diff = await container.registry.diff(refreshed.id)
    assert "description" in diff.changed_fields


async def test_rejected_tool_stays_rejected_after_flapping(container) -> None:
    upstream, _ = await register_and_sync(container, "weather", "weather")
    await detach(container, upstream.id)
    tool = await _first_tool(container, "weather__get_forecast")
    original = ToolDefinition.model_validate(tool.current_definition)
    await container.registry.approve(tool.id, tool.current_hash, "user:alice")
    await container.registry.reject(tool.id, "user:alice", "changed my mind")

    drifted = original.model_copy(update={"description": original.description + " (v2)"})
    await container.registry.reconcile(upstream.id, [drifted, _alerts_def()])
    await container.registry.reconcile(upstream.id, [original, _alerts_def()])

    flapped = await _first_tool(container, "weather__get_forecast")
    assert flapped.status is ToolStatus.REJECTED
    assert flapped.approved_hash is None
    assert "weather__get_forecast" not in {t.exposed_name for t in await container.registry.servable_tools()}
    detail = await container.registry.tool_detail(tool.id)
    assert len(detail.pins) == 1  # the history of what was once approved is kept


async def test_rejecting_quarantined_tool_drops_pin(container) -> None:
    upstream, _ = await register_and_sync(container, "weather", "weather")
    await detach(container, upstream.id)
    tool = await _first_tool(container, "weather__get_forecast")
    original = ToolDefinition.model_validate(tool.current_definition)
    await container.registry.approve(tool.id, tool.current_hash, "user:alice")
    drifted = original.model_copy(update={"description": "Something else entirely."})
    await container.registry.reconcile(upstream.id, [drifted, _alerts_def()])
    await container.registry.reject(tool.id, "user:alice")
    await container.registry.reconcile(upstream.id, [original, _alerts_def()])
    assert (await _first_tool(container, "weather__get_forecast")).status is ToolStatus.REJECTED


async def test_changed_rejected_tool_stays_out_of_review_queue(container) -> None:
    upstream, _ = await register_and_sync(container, "weather", "weather")
    await detach(container, upstream.id)
    tool = await _first_tool(container, "weather__get_forecast")
    original = ToolDefinition.model_validate(tool.current_definition)
    await container.registry.reject(tool.id, "user:alice", "not needed")

    edited = original.model_copy(update={"description": original.description + " Now with hourly data."})
    result = await container.registry.reconcile(upstream.id, [edited, _alerts_def()])

    assert "weather__get_forecast" in result.changed
    refreshed = await _first_tool(container, "weather__get_forecast")
    assert refreshed.status is ToolStatus.REJECTED
    queued = {item.tool.exposed_name for item in await container.registry.approval_queue()}
    assert "weather__get_forecast" not in queued

    # An admin can still approve the new definition on purpose.
    approved = await container.registry.approve(refreshed.id, refreshed.current_hash, "user:alice")
    assert approved.status is ToolStatus.APPROVED


async def test_approval_refuses_unenforceable_schema(container) -> None:
    from toolgate.errors import UnprocessableError

    upstream, _ = await register_and_sync(container, "weather", "weather")
    await detach(container, upstream.id)
    broken = ToolDefinition(
        name="get_forecast",
        description="Daily forecast for a city.",
        input_schema={"type": "object", "properties": {"city": {"type": "string", "pattern": "(unclosed"}}},
    )
    await container.registry.reconcile(upstream.id, [broken, _alerts_def()])
    tool = await _first_tool(container, "weather__get_forecast")
    with pytest.raises(UnprocessableError):
        await container.registry.approve(tool.id, tool.current_hash, "user:alice")
