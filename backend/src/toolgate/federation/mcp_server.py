from __future__ import annotations

from typing import Any

import mcp_types as types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from starlette.requests import Request
from starlette.types import ASGIApp

from toolgate import __version__
from toolgate.auth.middleware import BearerAuthMiddleware, principal_from_scope
from toolgate.auth.scopes import MCP_SCOPES
from toolgate.auth.tokens import TokenService
from toolgate.common.principal import Principal
from toolgate.config import Settings
from toolgate.federation.gateway import GatewayService

INSTRUCTIONS = (
    "Toolgate federates several MCP servers. Tool names are namespaced as <server>__<tool>. "
    "Only tools an administrator has reviewed and pinned are listed, and every call is policy-checked and audited."
)


def _principal(ctx: ServerRequestContext[Any, Any]) -> Principal:
    request = ctx.request
    principal = principal_from_scope(request.scope) if isinstance(request, Request) else None
    if principal is None:
        raise MCPError(types.INVALID_REQUEST, "Unauthenticated request reached the MCP handler")
    return principal


def build_mcp_server(gateway: GatewayService) -> Server[Any]:
    async def on_list_tools(
        ctx: ServerRequestContext[Any, Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=await gateway.list_tools(_principal(ctx)))

    async def on_call_tool(
        ctx: ServerRequestContext[Any, Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        return await gateway.call_tool(_principal(ctx), params.name, params.arguments, rpc_id=ctx.request_id)

    return Server(
        "toolgate",
        version=__version__,
        title="Toolgate",
        description="Zero-trust MCP gateway",
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


class McpEndpoint:
    """Streamable HTTP endpoint for the federated server. Stateless, so any replica can serve any request."""

    def __init__(self, gateway: GatewayService, tokens: TokenService, settings: Settings) -> None:
        self.server = build_mcp_server(gateway)
        self.session_manager = StreamableHTTPSessionManager(
            app=self.server,
            stateless=True,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=settings.mcp_allowed_hosts,
                allowed_origins=settings.mcp_allowed_origins,
            ),
        )
        self.asgi: ASGIApp = BearerAuthMiddleware(
            StreamableHTTPASGIApp(self.session_manager),
            tokens,
            audience=settings.mcp_resource,
            resource_metadata_url=f"{settings.issuer}/.well-known/oauth-protected-resource/mcp",
            required_scopes=MCP_SCOPES,
        )
