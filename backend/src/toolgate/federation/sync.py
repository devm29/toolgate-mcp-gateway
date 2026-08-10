from __future__ import annotations

import asyncio
import contextlib
import uuid

from toolgate.errors import ConflictError, UpstreamUnavailableError
from toolgate.federation.pool import SessionPool
from toolgate.logging import get_logger
from toolgate.registry.models import UpstreamStatus
from toolgate.registry.schemas import SyncResult
from toolgate.registry.service import RegistryService

log = get_logger(__name__)


class SyncService:
    """Pulls tools/list from upstreams and folds it into the registry, one sync per upstream at a time."""

    def __init__(self, registry: RegistryService, pool: SessionPool, *, timeout: float) -> None:
        self._registry = registry
        self._pool = pool
        self._timeout = timeout
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}
        self._background: set[asyncio.Task[None]] = set()

    async def sync(self, upstream_id: uuid.UUID) -> SyncResult:
        lock = self._locks.setdefault(upstream_id, asyncio.Lock())
        async with lock:
            upstream = await self._registry.get_upstream(upstream_id)
            connection = await self._pool.ensure(upstream)
            if connection is None:
                raise ConflictError(f"Upstream '{upstream.name}' is disabled")
            try:
                listed = await connection.list_tools(timeout=self._timeout)
            except UpstreamUnavailableError as exc:
                await self._registry.mark_upstream(upstream_id, UpstreamStatus.DEGRADED, exc.detail)
                raise
            except Exception as exc:
                message = f"tools/list failed: {exc}"[:300]
                await self._registry.mark_upstream(upstream_id, UpstreamStatus.DEGRADED, message)
                raise UpstreamUnavailableError(message) from exc
            result = await self._registry.reconcile(upstream_id, listed)
        if result.new or result.changed or result.removed or result.restored:
            log.info(
                "upstream_synced",
                upstream=result.upstream,
                new=len(result.new),
                changed=len(result.changed),
                quarantined=len(result.quarantined),
                removed=len(result.removed),
            )
        return result

    async def connect_all(self) -> None:
        upstreams = await self._registry.upstream_models()
        for upstream in upstreams:
            await self._pool.ensure(upstream)
        await self._pool.retain_only({u.id for u in upstreams if u.enabled})

    async def refresh_all(self) -> None:
        upstreams = [u for u in await self._registry.upstream_models() if u.enabled]
        results = await asyncio.gather(*(self._refresh_one(u.id) for u in upstreams), return_exceptions=True)
        for upstream, outcome in zip(upstreams, results, strict=True):
            if isinstance(outcome, Exception) and not isinstance(outcome, UpstreamUnavailableError):
                log.error("upstream_refresh_failed", upstream=upstream.name, error=str(outcome))

    async def _refresh_one(self, upstream_id: uuid.UUID) -> None:
        connection = self._pool.get(upstream_id)
        if connection is None or not connection.connected:
            return
        await self.sync(upstream_id)

    def schedule(self, upstream_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._safe_sync(upstream_id))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _safe_sync(self, upstream_id: uuid.UUID) -> None:
        try:
            await self.sync(upstream_id)
        except Exception as exc:
            log.warning("background_sync_failed", upstream_id=str(upstream_id), error=str(exc))

    async def on_status(self, upstream_id: uuid.UUID, connected: bool, error: str | None) -> None:
        if connected:
            # Every (re)connection gets a fresh listing: a server that swaps its tools across a restart
            # is caught the moment it comes back.
            self.schedule(upstream_id)
        else:
            await self._registry.mark_upstream(upstream_id, UpstreamStatus.DEGRADED, error)

    async def on_tools_changed(self, upstream_id: uuid.UUID) -> None:
        self.schedule(upstream_id)

    async def drain(self) -> None:
        for task in list(self._background):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


class Refresher:
    def __init__(self, sync: SyncService, *, interval: float) -> None:
        self._sync = sync
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="toolgate-refresher")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._sync.refresh_all()
            except Exception as exc:
                log.error("refresh_cycle_failed", error=str(exc))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
