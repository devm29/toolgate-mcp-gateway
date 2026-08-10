"""Tiny harness for the demo and red-team MCP servers.

Fixtures are written against the low-level server API on purpose: an attacker controls raw tool metadata
byte for byte, and a higher-level framework would normalize away exactly the tricks we need to reproduce.
"""

from __future__ import annotations

import argparse
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp_types as types
import uvicorn
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.subscriptions import ToolsListChanged
from starlette.applications import Starlette

Handler = Callable[[dict[str, Any]], Awaitable[Any] | Any]


@dataclass
class FixtureTool:
    name: str
    description: str | Callable[[], str]
    input_schema: dict[str, Any]
    handler: Handler
    title: str | None = None
    annotations: dict[str, Any] | None = None

    def definition(self) -> types.Tool:
        description = self.description() if callable(self.description) else self.description
        return types.Tool.model_validate(
            {
                "name": self.name,
                "title": self.title,
                "description": description,
                "inputSchema": self.input_schema,
                "annotations": self.annotations,
            }
        )


@dataclass
class FixtureServer:
    name: str
    tools: Sequence[FixtureTool] | Callable[[], Sequence[FixtureTool]]
    version: str = "1.0.0"
    instructions: str | None = None
    list_hook: Callable[[], None] | None = None
    notify_after_call: bool = False
    _built: Server[Any] | None = field(default=None, init=False)
    _bus: InMemorySubscriptionBus = field(default_factory=InMemorySubscriptionBus, init=False)

    def current_tools(self) -> list[FixtureTool]:
        return list(self.tools() if callable(self.tools) else self.tools)

    def build(self) -> Server[Any]:
        if self._built is not None:
            return self._built

        async def on_list_tools(
            ctx: ServerRequestContext[Any, Any], params: types.PaginatedRequestParams | None
        ) -> types.ListToolsResult:
            if self.list_hook is not None:
                self.list_hook()
            return types.ListToolsResult(tools=[t.definition() for t in self.current_tools()])

        async def on_call_tool(
            ctx: ServerRequestContext[Any, Any], params: types.CallToolRequestParams
        ) -> types.CallToolResult:
            tool = next((t for t in self.current_tools() if t.name == params.name), None)
            if tool is None:
                return _text(f"Unknown tool {params.name}", error=True)
            try:
                outcome = tool.handler(dict(params.arguments or {}))
                if inspect.isawaitable(outcome):
                    outcome = await outcome
            except (KeyError, ValueError) as exc:
                return _text(f"Invalid arguments: {exc}", error=True)
            if self.notify_after_call:
                # Modern clients hear about it on their subscriptions/listen stream, older ones by notification.
                await self._bus.publish(ToolsListChanged())
                await ctx.session.send_tool_list_changed()
            if isinstance(outcome, str):
                return _text(outcome)
            return types.CallToolResult.model_validate(
                {
                    "content": [{"type": "text", "text": json.dumps(outcome, indent=2)}],
                    "structuredContent": outcome if isinstance(outcome, dict) else {"result": outcome},
                }
            )

        self._built = Server(
            self.name,
            version=self.version,
            instructions=self.instructions,
            on_list_tools=on_list_tools,
            on_call_tool=on_call_tool,
            on_subscriptions_listen=ListenHandler(self._bus) if self.notify_after_call else None,
        )
        return self._built

    def http_app(self, path: str = "/mcp") -> Starlette:
        return self.build().streamable_http_app(
            streamable_http_path=path,
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )

    async def serve_stdio(self) -> None:
        server = self.build()
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    def main(self, argv: Sequence[str] | None = None) -> None:
        parser = argparse.ArgumentParser(description=f"{self.name} MCP fixture server")
        parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=9000)
        args = parser.parse_args(argv)
        if args.transport == "stdio":
            anyio.run(self.serve_stdio)
        else:
            uvicorn.run(self.http_app(), host=args.host, port=args.port, log_level="warning")


def _text(text: str, *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult.model_validate({"content": [{"type": "text", "text": text}], "isError": error})


def schema(properties: dict[str, dict[str, Any]], required: Sequence[str] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}
