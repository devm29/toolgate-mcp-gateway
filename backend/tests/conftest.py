from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from toolgate.config import ClassifierBackend, Environment, OtelExporter, Settings
from toolgate.container import Container, build_container
from toolgate.db import Base, create_engine
from toolgate.models import import_all_models

import_all_models()

TEST_DB = os.environ.get("TOOLGATE_TEST_DATABASE_URL", "postgresql+asyncpg://toolgate@127.0.0.1:5501/toolgate_test")
TEST_REDIS = os.environ.get("TOOLGATE_TEST_REDIS_URL", "redis://127.0.0.1:6401/15")


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        env=Environment.TEST,
        database_url=TEST_DB,
        redis_url=TEST_REDIS,
        public_url="http://localhost:8101",  # type: ignore[arg-type]
        classifier=ClassifierBackend.OFFLINE,
        otel_exporter=OtelExporter.NONE,
        refresh_interval_seconds=3600,
        upstream_connect_timeout_seconds=5,
        upstream_call_timeout_seconds=8,
        access_token_ttl_seconds=600,
    )


async def _reset_schema(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP; END; $$ LANGUAGE plpgsql"
            )
        )
        await conn.execute(text("DROP TRIGGER IF EXISTS audit_events_no_mutation ON audit_events"))
        await conn.execute(
            text(
                "CREATE TRIGGER audit_events_no_mutation BEFORE UPDATE OR DELETE ON audit_events "
                "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
            )
        )
    await engine.dispose()


@pytest_asyncio.fixture
async def container(settings: Settings) -> AsyncIterator[Container]:
    await _reset_schema(settings)
    built = await build_container(settings)
    await built.redis.flushdb()
    try:
        yield built
    finally:
        await built.redis.flushdb()
        await built.close()


@pytest_asyncio.fixture
async def client(container: Container, settings: Settings) -> AsyncIterator[AsyncClient]:
    from toolgate.app import create_app

    app = create_app(settings, container=container, start_federation=False)
    async with LifespanManager(app) as managed:
        async with AsyncClient(transport=ASGITransport(app=managed.app), base_url=settings.issuer) as http:
            yield http


@pytest.fixture
def admin_headers(settings: Settings) -> dict[str, str]:
    return {"X-Toolgate-Admin-Key": settings.admin_api_key.get_secret_value()}
