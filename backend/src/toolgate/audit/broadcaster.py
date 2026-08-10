from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import ValidationError
from redis.asyncio import Redis

from toolgate.audit.schemas import AuditEventOut
from toolgate.logging import get_logger

CHANNEL = "toolgate:audit"
log = get_logger(__name__)


class AuditBroadcaster:
    """Fans audit events out through Redis pub/sub so every gateway replica's SSE clients see every call."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, event: AuditEventOut) -> None:
        await self._redis.publish(CHANNEL, event.model_dump_json())

    @asynccontextmanager
    async def listen(self) -> AsyncIterator[AsyncIterator[AuditEventOut]]:
        """Subscribes before yielding, so callers can replay history without a gap."""
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(CHANNEL)
        try:
            yield self._events(pubsub)
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis PubSub.aclose lacks a stub

    @staticmethod
    async def _events(pubsub: Any) -> AsyncIterator[AuditEventOut]:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                yield AuditEventOut.model_validate_json(message["data"])
            except ValidationError:
                log.warning("audit_broadcast_malformed")
