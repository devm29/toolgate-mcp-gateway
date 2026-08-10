from __future__ import annotations

import asyncio
import contextlib
import os
import random
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp_types as types
from mcp import Client, StdioServerParameters
from mcp.client.session import IncomingMessage
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.client.subscriptions import ListenNotSupportedError
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.exceptions import MCPError

from toolgate import __version__
from toolgate.common.tool_definition import ToolDefinition
from toolgate.errors import UpstreamUnavailableError
from toolgate.logging import get_logger
from toolgate.registry.models import Transport, Upstream

log = get_logger(__name__)

ToolsChangedCallback = Callable[[uuid.UUID], Awaitable[None]]
StatusCallback = Callable[[uuid.UUID, bool, str | None], Awaitable[None]]

MAX_LIST_PAGES = 50
_TRANSPORT_GONE = (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream)


@dataclass(frozen=True, slots=True)
class UpstreamSpec:
    """Connection settings snapshot; a change to any field means the connection must be rebuilt."""

    id: uuid.UUID
    name: str
    transport: Transport
    command: str | None
    args: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    cwd: str | None
    url: str | None
    headers: tuple[tuple[str, str], ...]

    @classmethod
    def from_model(cls, upstream: Upstream) -> UpstreamSpec:
        return cls(
            id=upstream.id,
            name=upstream.name,
            transport=upstream.transport,
            command=upstream.command,
            args=tuple(upstream.args),
            env=tuple(sorted(upstream.env.items())),
            cwd=upstream.cwd,
            url=upstream.url,
            headers=tuple(sorted(upstream.headers.items())),
        )


@dataclass
class _ConnectionState:
    client: Client | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    last_error: str | None = None


class UpstreamConnection:
    """One supervised MCP client session to one upstream server.

    The session's async context managers have to be entered and exited on the same task, so a dedicated
    supervisor task owns the session for its whole life and reconnects with jittered backoff. Callers on
    other tasks multiplex requests over it; JSON-RPC ids keep concurrent calls apart.

    A session can die without telling anyone (the process exits, the HTTP peer goes away), so the supervisor
    reconnects when a caller sees the transport closed and also pings the upstream on an interval.
    """

    def __init__(
        self,
        spec: UpstreamSpec,
        *,
        connect_timeout: float,
        max_concurrency: int,
        on_tools_changed: ToolsChangedCallback,
        on_status: StatusCallback,
        stderr_path: str | None = None,
        health_interval: float = 15.0,
    ) -> None:
        self.spec = spec
        self._connect_timeout = connect_timeout
        self._health_interval = health_interval
        self._limiter = asyncio.Semaphore(max_concurrency)
        self._on_tools_changed = on_tools_changed
        self._on_status = on_status
        self._stderr_path = stderr_path
        self._state = _ConnectionState()
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._broken: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._notify_tasks: set[asyncio.Task[None]] = set()

    @property
    def connected(self) -> bool:
        return self._state.ready.is_set()

    @property
    def last_error(self) -> str | None:
        return self._state.last_error

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._supervise(), name=f"upstream:{self.spec.name}")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _message_handler(self, message: IncomingMessage) -> None:
        if isinstance(message, types.ToolListChangedNotification):
            self._tools_changed()

    def _tools_changed(self) -> None:
        log.info("upstream_tools_changed", upstream=self.spec.name)
        task: asyncio.Task[None] = asyncio.create_task(self._notify_tools_changed())
        self._notify_tasks.add(task)
        task.add_done_callback(self._notify_tasks.discard)

    async def _follow_changes(self, client: Client) -> None:
        """From protocol 2026-07-28 on, list changes only arrive on a subscriptions/listen stream."""
        tools = client.server_capabilities.tools
        if tools is None or not tools.list_changed:
            return
        try:
            async with client.listen(tools_list_changed=True) as subscription:
                async for _ in subscription:
                    self._tools_changed()
        except ListenNotSupportedError:
            return  # older protocol: changes come in as notifications through _message_handler
        except Exception as exc:
            if self._broken is None and not self._stop.is_set():
                log.warning("upstream_listen_failed", upstream=self.spec.name, error=_describe(exc))

    async def _notify_tools_changed(self) -> None:
        await self._on_tools_changed(self.spec.id)

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[Client]:
        async with AsyncExitStack() as stack:
            if self.spec.transport is Transport.STDIO:
                if not self.spec.command:
                    raise ValueError("stdio upstream has no command")
                params = StdioServerParameters(
                    command=self.spec.command,
                    args=list(self.spec.args),
                    env=dict(self.spec.env) or None,
                    cwd=self.spec.cwd,
                )
                errlog = stack.enter_context(open(self._stderr_path or os.devnull, "a", encoding="utf-8"))  # noqa: SIM115
                transport: Any = stdio_client(params, errlog=errlog)
            else:
                if not self.spec.url:
                    raise ValueError("streamable_http upstream has no url")
                # The gateway never forwards the caller's credentials; only operator-configured headers go upstream.
                http = await stack.enter_async_context(create_mcp_http_client(headers=dict(self.spec.headers)))
                transport = streamable_http_client(self.spec.url, http_client=http)
            client = Client(
                transport,
                cache=None,
                message_handler=self._message_handler,
                client_info=types.Implementation(name="toolgate", version=__version__),
            )
            yield await stack.enter_async_context(client)

    async def _supervise(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            opened = self._open()
            try:
                async with asyncio.timeout(self._connect_timeout):
                    client = await opened.__aenter__()
            except Exception as exc:
                attempt += 1
                await self._mark_down(exc)
                await self._backoff(attempt)
                continue
            exc_info: tuple[Any, Any, Any] = (None, None, None)
            follower: asyncio.Task[None] | None = None
            try:
                attempt = 0
                self._broken = None
                self._wake.clear()
                self._state.client = client
                self._state.last_error = None
                self._state.ready.set()
                log.info("upstream_connected", upstream=self.spec.name, protocol=client.protocol_version)
                await self._on_status(self.spec.id, True, None)
                follower = asyncio.create_task(self._follow_changes(client), name=f"upstream-listen:{self.spec.name}")
                reason = await self._watch(client)
                if reason is not None:
                    await self._mark_down(ConnectionError(reason))
            except BaseException as exc:
                exc_info = sys.exc_info()
                if not isinstance(exc, Exception):
                    raise
                await self._mark_down(exc)
            finally:
                self._state.ready.clear()
                self._state.client = None
                if follower is not None:
                    follower.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await follower
                with contextlib.suppress(Exception):
                    await opened.__aexit__(*exc_info)
            if not self._stop.is_set():
                attempt += 1
                await self._backoff(attempt)

    async def _watch(self, client: Client) -> str | None:
        """Block while the session is healthy. Returns why it is not, or None when asked to stop."""
        while not self._stop.is_set():
            if self._broken is not None:
                return self._broken
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._health_interval)
                continue
            try:
                async with asyncio.timeout(self._connect_timeout):
                    await client.send_ping()
            except MCPError:
                # Any JSON-RPC reply, even "Method not found" from a server without ping, proves the peer is
                # alive. Treating it as a failure would restart every such upstream on each health interval.
                continue
            except (TimeoutError, *_TRANSPORT_GONE) as exc:
                return f"health check failed: {_describe(exc)}"
        return None

    def _signal_broken(self, reason: str) -> None:
        if self._broken is None:
            self._broken = reason
            self._state.ready.clear()
            self._wake.set()

    async def _mark_down(self, exc: BaseException) -> None:
        message = _describe(exc)
        self._state.ready.clear()
        self._state.client = None
        if message != self._state.last_error:
            log.warning("upstream_unavailable", upstream=self.spec.name, error=message)
        self._state.last_error = message
        with contextlib.suppress(Exception):
            await self._on_status(self.spec.id, False, message)

    async def _backoff(self, attempt: int) -> None:
        delay = min(30.0, 0.5 * 2 ** min(attempt, 6)) * random.uniform(0.8, 1.2)  # noqa: S311
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=delay)

    async def _client(self, timeout: float) -> Client:
        try:
            await asyncio.wait_for(self._state.ready.wait(), timeout=timeout)
        except TimeoutError as exc:
            reason = self._state.last_error or "not connected"
            raise UpstreamUnavailableError(f"Upstream '{self.spec.name}' is unavailable: {reason}") from exc
        client = self._state.client
        if client is None:
            raise UpstreamUnavailableError(f"Upstream '{self.spec.name}' is reconnecting")
        return client

    @contextlib.contextmanager
    def _detect_closed(self) -> Iterator[None]:
        try:
            yield
        except MCPError as exc:
            if exc.error.code != types.CONNECTION_CLOSED:
                raise
            self._signal_broken("connection closed")
            raise UpstreamUnavailableError(f"Upstream '{self.spec.name}' closed the connection; reconnecting") from exc
        except _TRANSPORT_GONE as exc:
            self._signal_broken("transport closed")
            raise UpstreamUnavailableError(f"Upstream '{self.spec.name}' closed the connection; reconnecting") from exc

    async def list_tools(self, *, timeout: float) -> list[ToolDefinition]:
        client = await self._client(timeout)
        definitions: list[ToolDefinition] = []
        cursor: str | None = None
        with self._detect_closed():
            async with self._limiter, asyncio.timeout(timeout):
                for _ in range(MAX_LIST_PAGES):
                    page = await client.list_tools(cursor=cursor, cache_mode="refresh")
                    definitions.extend(ToolDefinition.from_mcp(tool) for tool in page.tools)
                    cursor = page.next_cursor
                    if not cursor:
                        break
        return definitions

    async def call_tool(self, name: str, arguments: dict[str, Any], *, timeout: float) -> types.CallToolResult:
        client = await self._client(min(timeout, self._connect_timeout))
        with self._detect_closed():
            async with self._limiter:
                return await client.call_tool(name, arguments, read_timeout_seconds=timeout)


def _describe(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        leaves = exc.exceptions
        return _describe(leaves[0]) if leaves else type(exc).__name__
    text = str(exc) or type(exc).__name__
    return text[:300]


class SessionPool:
    """Owns one supervised connection per enabled upstream and keeps the set in line with the registry."""

    def __init__(
        self,
        *,
        connect_timeout: float,
        max_concurrency: int,
        on_tools_changed: ToolsChangedCallback,
        on_status: StatusCallback,
        stderr_dir: str | None = None,
        health_interval: float = 15.0,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._health_interval = health_interval
        self._max_concurrency = max_concurrency
        self._on_tools_changed = on_tools_changed
        self._on_status = on_status
        self._stderr_dir = stderr_dir
        self._connections: dict[uuid.UUID, UpstreamConnection] = {}
        self._lock = asyncio.Lock()

    def get(self, upstream_id: uuid.UUID) -> UpstreamConnection | None:
        return self._connections.get(upstream_id)

    def require(self, upstream_id: uuid.UUID, name: str) -> UpstreamConnection:
        connection = self._connections.get(upstream_id)
        if connection is None:
            raise UpstreamUnavailableError(f"Upstream '{name}' is not connected")
        return connection

    async def ensure(self, upstream: Upstream) -> UpstreamConnection | None:
        async with self._lock:
            existing = self._connections.get(upstream.id)
            if not upstream.enabled:
                if existing is not None:
                    await existing.stop()
                    del self._connections[upstream.id]
                return None
            spec = UpstreamSpec.from_model(upstream)
            if existing is not None and existing.spec == spec:
                return existing
            if existing is not None:
                await existing.stop()
            stderr = os.path.join(self._stderr_dir, f"{spec.name}.log") if self._stderr_dir else None
            connection = UpstreamConnection(
                spec,
                connect_timeout=self._connect_timeout,
                max_concurrency=self._max_concurrency,
                on_tools_changed=self._on_tools_changed,
                on_status=self._on_status,
                stderr_path=stderr,
                health_interval=self._health_interval,
            )
            self._connections[upstream.id] = connection
            connection.start()
            return connection

    async def remove(self, upstream_id: uuid.UUID) -> None:
        async with self._lock:
            connection = self._connections.pop(upstream_id, None)
        if connection is not None:
            await connection.stop()

    async def retain_only(self, upstream_ids: set[uuid.UUID]) -> None:
        for upstream_id in [uid for uid in self._connections if uid not in upstream_ids]:
            await self.remove(upstream_id)

    async def close(self) -> None:
        async with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
        await asyncio.gather(*(c.stop() for c in connections), return_exceptions=True)
