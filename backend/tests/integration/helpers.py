from __future__ import annotations

import asyncio
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn

from toolgate.container import Container
from toolgate.registry.models import Transport
from toolgate.registry.schemas import UpstreamCreate


def fixture_upstream(name: str, module: str, **over: Any) -> UpstreamCreate:
    return UpstreamCreate(
        name=name,
        display_name=over.pop("display_name", name.title()),
        description="",
        transport=Transport.STDIO,
        command=sys.executable,
        args=["-m", f"fixtures.servers.{module}", "--transport", "stdio"],
        **over,
    )


async def register_and_sync(container: Container, name: str, module: str) -> Any:
    upstream = await container.registry.create_upstream(fixture_upstream(name, module))
    await container.pool.ensure(await container.registry.get_upstream(upstream.id))
    result = await container.sync.sync(upstream.id)
    return upstream, result


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@asynccontextmanager
async def serve(app: Any, port: int) -> AsyncIterator[str]:
    """Run an ASGI app on a real socket, for clients that need streaming or a network peer."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.025)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)


async def wait_until(predicate: Any, *, within: float = 10.0, interval: float = 0.1) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while True:
        outcome = predicate()
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
        if outcome:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(interval)


async def detach(container: Container, upstream_id: Any) -> None:
    """Stop the live session so a test can feed reconcile() by hand without a background sync racing it."""
    await container.pool.remove(upstream_id)
    await container.sync.drain()
