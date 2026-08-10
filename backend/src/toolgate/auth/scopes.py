from __future__ import annotations

TOOLS_LIST = "mcp:tools.list"
TOOLS_CALL = "mcp:tools.call"
ADMIN = "toolgate:admin"

MCP_SCOPES = (TOOLS_LIST, TOOLS_CALL)
ALL_SCOPES = (*MCP_SCOPES, ADMIN)
DEFAULT_SCOPE = " ".join(MCP_SCOPES)

DESCRIPTIONS = {
    TOOLS_LIST: "See the tools your policies allow",
    TOOLS_CALL: "Call those tools through the gateway",
    ADMIN: "Manage servers, approvals and policies",
}


def parse(scope: str | None) -> list[str]:
    seen: list[str] = []
    for item in (scope or "").split():
        if item not in seen:
            seen.append(item)
    return seen


def render(scopes: list[str] | tuple[str, ...] | frozenset[str]) -> str:
    return " ".join(sorted(scopes, key=lambda s: ALL_SCOPES.index(s) if s in ALL_SCOPES else len(ALL_SCOPES)))
