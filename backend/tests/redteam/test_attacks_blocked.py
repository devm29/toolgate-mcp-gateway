"""Each test drives a bundled malicious MCP server through the real gateway and asserts the attack is blocked.

With TOOLGATE_WRITE_ATTACK_REPORT=1 (`make attack-report`) the outcomes are written to docs/attack-blocked.json,
which the README's attack-blocked table is built from.
"""

from __future__ import annotations

import pytest

from tests.integration.helpers import register_and_sync
from tests.redteam.conftest import record_attack
from toolgate.audit.schemas import Decision
from toolgate.common.principal import Principal
from toolgate.policy.schemas import PolicyCreate, PolicyRule
from toolgate.registry.models import ToolStatus
from toolgate.scanner.models import RiskLevel

pytestmark = [pytest.mark.asyncio, pytest.mark.redteam]

AGENT = Principal(subject="user:agent", scopes=frozenset({"mcp:tools.list", "mcp:tools.call"}))


async def _allow_all(container) -> None:
    await container.policies.create(
        PolicyCreate(name="allow-all", rules=[PolicyRule(id="all", effect="allow", tools=["*"])])
    )


async def _tool(container, exposed: str):
    tool = await container.registry.find_exposed(exposed)
    assert tool is not None, exposed
    return tool


async def test_tool_poisoning_scored_high_and_never_exposed(container) -> None:
    upstream, _ = await register_and_sync(container, "mathtools", "poisoned")
    await _allow_all(container)
    tool = await _tool(container, "mathtools__add")
    assert tool.status is ToolStatus.PENDING
    assert tool.risk_level in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value}
    assert "mathtools__add" not in {t.name for t in await container.gateway.list_tools(AGENT)}
    result = await container.gateway.call_tool(AGENT, "mathtools__add", {"a": 1, "b": 2})
    assert result.is_error
    record_attack(
        attack="Tool poisoning",
        technique="Hidden <IMPORTANT> instruction block directing the model to read secret files",
        fixture="fixtures/servers/poisoned.py",
        decision="scanned high-risk, quarantined pending review, call blocked",
        detail=f"risk={tool.risk_level} score={tool.risk_score}",
    )


async def test_rug_pull_quarantined_after_approval(container, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUG_PULL_AFTER_LISTS", "1")
    upstream, _ = await register_and_sync(container, "notes", "rug_pull")
    await _allow_all(container)
    tool = await _tool(container, "notes__summarize_release")
    await container.registry.approve(tool.id, tool.current_hash, "user:admin")
    assert "notes__summarize_release" in {t.name for t in await container.gateway.list_tools(AGENT)}

    # Second sync pulls the swapped definition; the pin must catch the drift.
    await container.sync.sync(upstream.id)
    drifted = await _tool(container, "notes__summarize_release")
    assert drifted.status is ToolStatus.QUARANTINED
    result = await container.gateway.call_tool(AGENT, "notes__summarize_release", {"version": "v1.2.3"})
    assert result.is_error
    page = await container.audit.page(_f(), cursor=None, limit=5)
    assert page.items[0].decision is Decision.QUARANTINED
    record_attack(
        attack="Rug pull",
        technique="Definition changed after approval (silent description swap)",
        fixture="fixtures/servers/rug_pull.py",
        decision="SHA-256 pin mismatch, re-quarantined, call blocked",
        detail="approved hash no longer matches upstream hash",
    )


async def test_cross_tool_shadowing_detected(container) -> None:
    await register_and_sync(container, "mailer", "mailer")
    upstream, _ = await register_and_sync(container, "mailhelper", "shadowing")
    tool = await _tool(container, "mailhelper__format_signature")
    report = tool.scan_report
    rules = {f["rule"] for f in report["findings"]}
    assert "cross-tool-shadowing" in rules
    assert tool.risk_level in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value}
    record_attack(
        attack="Cross-tool shadowing",
        technique="Tool claims authority over another server's send_email tool",
        fixture="fixtures/servers/shadowing.py",
        decision="shadowing rule fired, quarantined pending review",
        detail=f"risk={tool.risk_level}",
    )


async def test_unicode_smuggling_detected(container) -> None:
    await register_and_sync(container, "translator", "unicode_smuggling")
    tool = await _tool(container, "translator__translate")
    rules = {f["rule"] for f in tool.scan_report["findings"]}
    assert "unicode-smuggling" in rules
    record_attack(
        attack="Unicode smuggling",
        technique="Invisible Unicode tag characters encode hidden text",
        fixture="fixtures/servers/unicode_smuggling.py",
        decision="invisible code points decoded and flagged, quarantined",
        detail=f"risk={tool.risk_level}",
    )


async def test_secret_file_read_blocked_by_policy(container) -> None:
    upstream, _ = await register_and_sync(container, "files", "files")
    tool = await _tool(container, "files__read_file")
    await container.registry.approve(tool.id, tool.current_hash, "user:admin")
    await container.policies.create(
        PolicyCreate(
            name="files",
            rules=[
                PolicyRule(id="allow", effect="allow", tools=["files__read_file"]),
                PolicyRule(
                    id="deny-secrets",
                    effect="deny",
                    tools=["files__read_file"],
                    arguments={
                        "type": "object",
                        "properties": {"path": {"type": "string", "pattern": "(\\.ssh/|/etc/|id_rsa)"}},
                        "required": ["path"],
                    },
                ),
            ],
        )
    )
    ok = await container.gateway.call_tool(AGENT, "files__read_file", {"path": "/workspace/README.md"})
    assert not ok.is_error
    blocked = await container.gateway.call_tool(AGENT, "files__read_file", {"path": "/home/dev/.ssh/id_rsa"})
    assert blocked.is_error
    record_attack(
        attack="Credential file read",
        technique="Agent coaxed into reading ~/.ssh/id_rsa through an approved file tool",
        fixture="fixtures/servers/files.py",
        decision="argument policy denied the path, call blocked and audited",
        detail="deny rule matched the secret-path pattern",
    )


async def test_argument_injection_rejected_by_pinned_schema(container) -> None:
    upstream, _ = await register_and_sync(container, "github", "github")
    tool = await _tool(container, "github__create_issue")
    await container.registry.approve(tool.id, tool.current_hash, "user:admin")
    await _allow_all(container)
    # The upstream schema forbids extra properties; a smuggled field is rejected before the upstream is touched.
    result = await container.gateway.call_tool(
        AGENT, "github__create_issue", {"repo": "acme/web", "title": "Looks fine", "__proto__": {"admin": True}}
    )
    assert result.is_error
    record_attack(
        attack="Argument injection",
        technique="Extra unexpected argument smuggled into a tools/call",
        fixture="fixtures/servers/github.py",
        decision="rejected against the pinned input schema (additionalProperties: false)",
        detail="schema validation ran before the upstream call",
    )


def _f(**kw):
    from toolgate.audit.schemas import AuditFilters

    return AuditFilters(**kw)


async def test_live_rug_pull_announced_with_list_changed(container) -> None:
    from tests.integration.helpers import wait_until

    await register_and_sync(container, "hotswap", "hot_swap")
    for exposed in ("hotswap__read_status", "hotswap__set_mode"):
        tool = await _tool(container, exposed)
        await container.registry.approve(tool.id, tool.current_hash, "user:admin")
    await _allow_all(container)

    flipped = await container.gateway.call_tool(AGENT, "hotswap__set_mode", {"mode": "verbose"})
    assert not flipped.is_error

    async def quarantined() -> bool:
        return (await _tool(container, "hotswap__read_status")).status is ToolStatus.QUARANTINED

    # No poll interval is involved: the upstream's own change announcement triggers the re-sync.
    await wait_until(quarantined, within=10)
    blocked = await container.gateway.call_tool(AGENT, "hotswap__read_status", {})
    assert blocked.is_error
    record_attack(
        attack="Live rug pull",
        technique="Definition changed mid-session and announced with tools/list_changed",
        fixture="fixtures/servers/hot_swap.py",
        decision="immediate re-sync, pin mismatch, quarantined, call blocked",
        detail="no polling interval involved",
    )
