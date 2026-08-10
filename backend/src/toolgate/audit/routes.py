from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from sse_starlette.sse import EventSourceResponse

from toolgate.audit.schemas import AuditEventOut, AuditFilters, AuditStats
from toolgate.auth.dependencies import AdminPrincipal
from toolgate.common.pagination import CursorPage
from toolgate.container import Container, get_container

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
ContainerDep = Annotated[Container, Depends(get_container)]
RECONNECT_DELAY_MS = 3000


@router.get("", response_model=CursorPage[AuditEventOut])
async def list_events(
    container: ContainerDep,
    _: AdminPrincipal,
    filters: Annotated[AuditFilters, Depends()],
    cursor: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CursorPage[AuditEventOut]:
    return await container.audit.page(filters, cursor=cursor, limit=limit)


@router.get("/stats", response_model=AuditStats)
async def stats(
    container: ContainerDep, _: AdminPrincipal, hours: Annotated[int, Query(ge=1, le=168)] = 24
) -> AuditStats:
    return await container.audit.stats(hours=hours)


@router.get("/stream")
async def stream(
    request: Request,
    container: ContainerDep,
    _: AdminPrincipal,
    last_event_id: Annotated[str | None, Header()] = None,
) -> EventSourceResponse:
    """Live call feed. Reconnecting clients send Last-Event-ID and get the gap replayed from Postgres."""

    async def events() -> AsyncIterator[dict[str, Any]]:
        async with container.broadcaster.listen() as feed:
            queue: asyncio.Queue[AuditEventOut] = asyncio.Queue(maxsize=1000)

            async def pump() -> None:
                async for event in feed:
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(event)

            task = asyncio.create_task(pump())
            try:
                # Write a frame straight away: relays such as the console's route handler only flush the response
                # headers with the first body chunk, so without it the client sat on "connecting" until the first
                # keep-alive ping 15 seconds later.
                yield {"retry": RECONNECT_DELAY_MS, "comment": "connected"}
                high_water = 0
                if last_event_id and last_event_id.isdigit():
                    for event in await container.audit.replay_after(int(last_event_id)):
                        high_water = event.id
                        yield {"id": str(event.id), "event": "audit", "data": event.model_dump_json()}
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        continue
                    if event.id <= high_water:
                        continue
                    yield {"id": str(event.id), "event": "audit", "data": event.model_dump_json()}
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    return EventSourceResponse(events(), ping=15, headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
