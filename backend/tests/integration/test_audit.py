from __future__ import annotations

import pytest
from sqlalchemy import text

from toolgate.audit.schemas import AuditEventCreate, AuditFilters, Decision

pytestmark = pytest.mark.asyncio


async def test_record_redacts_arguments(container) -> None:
    out = await container.audit.record(
        AuditEventCreate(
            request_id="r1",
            principal="user:alice",
            tool_name="files__read_file",
            decision=Decision.ALLOWED,
            arguments={"path": "/x", "password": "hunter2"},
        )
    )
    assert out.arguments["password"] == "[REDACTED]"
    assert out.arguments["path"] == "/x"


async def test_audit_log_is_append_only(container) -> None:
    await container.audit.record(
        AuditEventCreate(request_id="r", principal="p", tool_name="t", decision=Decision.ALLOWED)
    )
    with pytest.raises(Exception) as exc:
        async with container.engine.begin() as conn:
            await conn.execute(text("UPDATE audit_events SET reason = 'tampered'"))
    assert "append-only" in str(exc.value)


async def test_stats_counts_decisions(container) -> None:
    for decision in (Decision.ALLOWED, Decision.ALLOWED, Decision.DENIED):
        await container.audit.record(
            AuditEventCreate(request_id="r", principal="p", tool_name="weather__x", decision=decision)
        )
    stats = await container.audit.stats(hours=24)
    assert stats.allowed == 2
    assert stats.blocked == 1
    assert stats.total == 3
    assert stats.top_tools[0].tool_name == "weather__x"


async def test_cursor_pagination(container) -> None:
    for i in range(5):
        await container.audit.record(
            AuditEventCreate(request_id=f"r{i}", principal="p", tool_name="t", decision=Decision.ALLOWED)
        )
    first = await container.audit.page(AuditFilters(), cursor=None, limit=2)
    assert len(first.items) == 2
    assert first.next_cursor is not None
    second = await container.audit.page(AuditFilters(), cursor=first.next_cursor, limit=2)
    assert len(second.items) == 2
    assert second.items[0].id < first.items[-1].id
