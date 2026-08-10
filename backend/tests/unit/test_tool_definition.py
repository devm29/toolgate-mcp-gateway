from __future__ import annotations

from toolgate.common.tool_definition import ToolDefinition


def test_hash_is_stable_across_key_order() -> None:
    a = ToolDefinition(
        name="t", description="d", input_schema={"type": "object", "properties": {"x": {"type": "string"}}}
    )
    b = ToolDefinition(
        name="t", description="d", input_schema={"properties": {"x": {"type": "string"}}, "type": "object"}
    )
    assert a.sha256() == b.sha256()


def test_hash_changes_with_description() -> None:
    a = ToolDefinition(name="t", description="one")
    b = ToolDefinition(name="t", description="two")
    assert a.sha256() != b.sha256()


def test_invisible_characters_change_hash() -> None:
    a = ToolDefinition(name="t", description="hello")
    b = ToolDefinition(name="t", description="hello\u200b")
    assert a.sha256() != b.sha256()
    assert "\\u200b" in b.canonical_json()
