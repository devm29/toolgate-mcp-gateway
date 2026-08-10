from __future__ import annotations

import contextlib
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from fastapi import Request
from opentelemetry.sdk.trace import TracerProvider
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from toolgate.audit.broadcaster import AuditBroadcaster
from toolgate.audit.service import AuditService
from toolgate.audit.telemetry import TRACER_NAME, build_tracer_provider
from toolgate.auth.keys import KeyStore
from toolgate.auth.service import OAuthService
from toolgate.auth.sessions import LoginSessions
from toolgate.auth.tokens import TokenService
from toolgate.config import ClassifierBackend, Settings
from toolgate.db import SessionFactory, create_engine, create_session_factory
from toolgate.federation.gateway import GatewayService
from toolgate.federation.pool import SessionPool
from toolgate.federation.sync import Refresher, SyncService
from toolgate.logging import get_logger
from toolgate.policy.ratelimit import RateLimiter
from toolgate.policy.schemas import RateLimit
from toolgate.policy.service import PolicyService
from toolgate.registry.service import RegistryService
from toolgate.scanner.classifier import AnthropicClassifier, OfflineClassifier, ToolClassifier
from toolgate.scanner.pipeline import Scanner

log = get_logger(__name__)


def build_classifier(settings: Settings) -> ToolClassifier | None:
    if settings.classifier is ClassifierBackend.NONE:
        return None
    if settings.classifier is ClassifierBackend.ANTHROPIC:
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        client = anthropic.AsyncAnthropic(api_key=key) if key else anthropic.AsyncAnthropic()
        return AnthropicClassifier(client, settings.anthropic_model)
    return OfflineClassifier()


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    sessions: SessionFactory
    redis: Redis
    keys: KeyStore
    tokens: TokenService
    oauth: OAuthService
    login_sessions: LoginSessions
    rate_limiter: RateLimiter
    scanner: Scanner
    registry: RegistryService
    policies: PolicyService
    audit: AuditService
    broadcaster: AuditBroadcaster
    tracer_provider: TracerProvider
    pool: SessionPool
    sync: SyncService
    refresher: Refresher
    gateway: GatewayService
    registration_limit: RateLimit = field(default_factory=lambda: RateLimit(capacity=20, refill_per_minute=20))
    login_limit: RateLimit = field(default_factory=lambda: RateLimit(capacity=10, refill_per_minute=10))

    async def start_federation(self, *, refresh: bool = True) -> None:
        await self.sync.connect_all()
        if refresh:
            self.refresher.start()

    async def close(self) -> None:
        await self.refresher.stop()
        await self.sync.drain()
        await self.pool.close()
        with contextlib.suppress(Exception):
            self.tracer_provider.shutdown()
        await self.redis.aclose()
        await self.engine.dispose()


async def build_container(settings: Settings, *, tracer_provider: TracerProvider | None = None) -> Container:
    engine = create_engine(settings.database_url, pool_size=settings.database_pool_size)
    sessions = create_session_factory(engine)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)

    keys = KeyStore(sessions)
    await keys.load()
    tokens = TokenService(keys, redis, issuer=settings.issuer, ttl_seconds=settings.access_token_ttl_seconds)
    oauth = OAuthService(sessions, tokens, settings)
    await oauth.ensure_console_client()
    login_sessions = LoginSessions(
        settings.session_secret.get_secret_value(),
        ttl_seconds=settings.login_session_ttl_seconds,
        secure=settings.secure_cookies,
    )

    scanner = Scanner(build_classifier(settings))
    registry = RegistryService(sessions, scanner, auto_approve_clean=settings.auto_approve_clean_tools)
    policies = PolicyService(sessions)
    limiter = RateLimiter(redis)
    broadcaster = AuditBroadcaster(redis)
    audit = AuditService(sessions, broadcaster)
    provider = tracer_provider or build_tracer_provider(settings)

    stderr_dir = Path(os.environ.get("TOOLGATE_UPSTREAM_LOG_DIR", ".data/upstream-logs"))
    with contextlib.suppress(OSError):
        stderr_dir.mkdir(parents=True, exist_ok=True)

    sync_ref: list[SyncService] = []

    async def on_status(upstream_id: uuid.UUID, connected: bool, error: str | None) -> None:
        await sync_ref[0].on_status(upstream_id, connected, error)

    async def on_tools_changed(upstream_id: uuid.UUID) -> None:
        await sync_ref[0].on_tools_changed(upstream_id)

    pool = SessionPool(
        connect_timeout=settings.upstream_connect_timeout_seconds,
        max_concurrency=settings.upstream_max_concurrency,
        on_tools_changed=on_tools_changed,
        on_status=on_status,
        stderr_dir=str(stderr_dir) if stderr_dir.exists() else None,
        health_interval=settings.upstream_health_interval_seconds,
    )
    sync = SyncService(registry, pool, timeout=settings.upstream_call_timeout_seconds)
    sync_ref.append(sync)

    gateway = GatewayService(
        registry=registry,
        policies=policies,
        limiter=limiter,
        pool=pool,
        audit=audit,
        tracer=provider.get_tracer(TRACER_NAME),
        call_timeout=settings.upstream_call_timeout_seconds,
    )
    container = Container(
        settings=settings,
        engine=engine,
        sessions=sessions,
        redis=redis,
        keys=keys,
        tokens=tokens,
        oauth=oauth,
        login_sessions=login_sessions,
        rate_limiter=limiter,
        scanner=scanner,
        registry=registry,
        policies=policies,
        audit=audit,
        broadcaster=broadcaster,
        tracer_provider=provider,
        pool=pool,
        sync=sync,
        refresher=Refresher(sync, interval=settings.refresh_interval_seconds),
        gateway=gateway,
    )
    container.registration_limit = RateLimit(
        capacity=settings.registration_rate_per_minute, refill_per_minute=settings.registration_rate_per_minute
    )
    return container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container
