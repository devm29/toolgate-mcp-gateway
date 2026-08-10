"""The test suite builds its schema with create_all, so this guards the real migration path against drift."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DB

pytestmark = pytest.mark.asyncio

BACKEND = Path(__file__).resolve().parents[2]
SCRATCH_DB = "toolgate_migration_check"
APP_ROLE = "toolgate_migration_app"


def _dsn(database: str, user: str | None = None) -> str:
    url = make_url(TEST_DB).set(drivername="postgresql", database=database)
    if user:
        url = url.set(username=user, password=None)
    return url.render_as_string(hide_password=False)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "TOOLGATE_DATABASE_URL": make_url(TEST_DB).set(database=SCRATCH_DB).render_as_string(hide_password=False),
        "TOOLGATE_DB_APP_ROLE": APP_ROLE,
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, check=False
    )


async def test_migrations_apply_cleanly_and_match_models() -> None:
    admin = await asyncpg.connect(_dsn("postgres"))
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {SCRATCH_DB}")
        if not await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", APP_ROLE):
            await admin.execute(f"CREATE ROLE {APP_ROLE} LOGIN")
    finally:
        await admin.close()

    upgrade = _alembic("upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    check = _alembic("check")
    assert check.returncode == 0, check.stdout + check.stderr

    app = await asyncpg.connect(_dsn(SCRATCH_DB, APP_ROLE))
    try:
        await app.execute(
            "INSERT INTO audit_events (occurred_at, request_id, principal, tool_name, decision, reason, arguments,"
            " latency_ms, is_error) VALUES (now(), 'r', 'p', 't', 'allowed', '', '{}', 0, false)"
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app.execute("UPDATE audit_events SET reason = 'tampered'")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app.execute("DROP TRIGGER audit_events_no_mutation ON audit_events")
    finally:
        await app.close()

    downgrade = _alembic("downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr
