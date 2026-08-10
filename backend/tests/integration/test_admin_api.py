from __future__ import annotations

import asyncio
import json
import sys
import uuid

import httpx
import pytest
from httpx import AsyncClient

from tests.integration.helpers import fixture_upstream, free_port, serve
from tests.integration.oauth_helpers import authorize, exchange, register_public_client
from toolgate.audit.schemas import AuditEventCreate, Decision
from toolgate.config import CONSOLE_CLIENT_ID

pytestmark = pytest.mark.asyncio


async def _admin_token(client: AsyncClient, container, settings) -> str:
    await container.oauth.ensure_user("alice", "pw", display_name="Alice", is_admin=True)
    grant = await authorize(
        client,
        CONSOLE_CLIENT_ID,
        scope="toolgate:admin",
        resource=settings.admin_resource,
        redirect_uri=settings.console_redirect_uri,
    )
    response = await exchange(client, grant, resource=settings.admin_resource)
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


async def test_admin_api_requires_credentials(client: AsyncClient) -> None:
    response = await client.get("/api/v1/upstreams")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_admin_api_rejects_wrong_key(client: AsyncClient) -> None:
    response = await client.get("/api/v1/upstreams", headers={"X-Toolgate-Admin-Key": "nope"})
    assert response.status_code == 401


async def test_admin_api_accepts_key(client: AsyncClient, admin_headers) -> None:
    assert (await client.get("/api/v1/upstreams", headers=admin_headers)).status_code == 200


async def test_console_login_yields_per_user_admin_token(client: AsyncClient, container, settings) -> None:
    token = await _admin_token(client, container, settings)
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/overview", headers=headers)).status_code == 200

    upstream = await container.registry.create_upstream(fixture_upstream("weather", "weather"))
    await container.pool.ensure(await container.registry.get_upstream(upstream.id))
    await container.sync.sync(upstream.id)
    tool = await container.registry.find_exposed("weather__get_forecast")
    approved = await client.post(
        f"/api/v1/tools/{tool.id}/approve", headers=headers, json={"expected_hash": tool.current_hash}
    )
    assert approved.status_code == 200
    # Approvals are attributed to the person who signed in, not to a shared console identity.
    assert approved.json()["approved_by"] == "user:alice"


async def test_mcp_token_cannot_call_admin_api(client: AsyncClient, container) -> None:
    await container.oauth.ensure_user("alice", "pw", display_name="Alice", is_admin=True)
    client_id = await register_public_client(client)
    mcp_token = (await exchange(client, await authorize(client, client_id))).json()["access_token"]
    response = await client.get("/api/v1/upstreams", headers={"Authorization": f"Bearer {mcp_token}"})
    assert response.status_code == 401


async def test_admin_audience_without_admin_scope_is_forbidden(client: AsyncClient, container, settings) -> None:
    issued = container.tokens.issue(
        subject="user:bob", client_id="tg_x", scopes=["mcp:tools.list"], resource=settings.admin_resource
    )
    response = await client.get("/api/v1/upstreams", headers={"Authorization": f"Bearer {issued.token}"})
    assert response.status_code == 403


async def test_upstream_patch_keeps_secrets(client: AsyncClient, admin_headers) -> None:
    created = await client.post(
        "/api/v1/upstreams",
        headers=admin_headers,
        json={
            "name": "secrets",
            "display_name": "Secrets",
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "fixtures.servers.weather"],
            "env": {"API_TOKEN": "s3cret"},
            "cwd": "/tmp",
            "enabled": False,
        },
    )
    assert created.status_code == 201, created.text
    upstream = created.json()
    assert upstream["env"] == {"API_TOKEN": "••••••"}

    toggled = await client.patch(f"/api/v1/upstreams/{upstream['id']}", headers=admin_headers, json={"enabled": False})
    assert toggled.status_code == 200
    renamed = await client.patch(
        f"/api/v1/upstreams/{upstream['id']}",
        headers=admin_headers,
        json={"display_name": "Renamed", "env": {"API_TOKEN": "••••••", "REGION": "eu"}},
    )
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Renamed"


async def test_upstream_patch_preserves_env_in_storage(client: AsyncClient, admin_headers, container) -> None:
    created = (
        await client.post(
            "/api/v1/upstreams",
            headers=admin_headers,
            json={
                "name": "keep",
                "display_name": "Keep",
                "transport": "stdio",
                "command": sys.executable,
                "env": {"API_TOKEN": "s3cret"},
                "headers": {},
                "cwd": "/tmp",
                "enabled": False,
            },
        )
    ).json()
    await client.patch(f"/api/v1/upstreams/{created['id']}", headers=admin_headers, json={"enabled": False})
    await client.patch(
        f"/api/v1/upstreams/{created['id']}",
        headers=admin_headers,
        json={"env": {"API_TOKEN": "••••••", "REGION": "eu"}},
    )
    stored = await container.registry.get_upstream(uuid.UUID(created["id"]))
    assert stored.env == {"API_TOKEN": "s3cret", "REGION": "eu"}
    assert stored.cwd == "/tmp"


async def test_upstream_patch_rejects_null_required_field(client: AsyncClient, admin_headers) -> None:
    created = (
        await client.post(
            "/api/v1/upstreams",
            headers=admin_headers,
            json={"name": "nulls", "display_name": "N", "transport": "stdio", "command": "x", "enabled": False},
        )
    ).json()
    response = await client.patch(
        f"/api/v1/upstreams/{created['id']}", headers=admin_headers, json={"display_name": None}
    )
    assert response.status_code == 422


async def test_audit_stream_delivers_live_events_and_replays_gap(container, settings, admin_headers) -> None:
    from toolgate.app import create_app

    before = await container.audit.record(
        AuditEventCreate(request_id="r0", principal="user:a", tool_name="t__x", decision=Decision.ALLOWED)
    )
    app = create_app(settings, container=container, start_federation=False)
    async with serve(app, free_port()) as base:
        async with httpx.AsyncClient(base_url=base, timeout=10) as http:
            headers = {**admin_headers, "Last-Event-ID": str(before.id - 1)}
            async with http.stream("GET", "/api/v1/audit/stream", headers=headers) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                received: list[dict[str, object]] = []

                async def publish_later() -> None:
                    await asyncio.sleep(0.3)
                    await container.audit.record(
                        AuditEventCreate(
                            request_id="r1", principal="user:a", tool_name="t__y", decision=Decision.DENIED
                        )
                    )

                publisher = asyncio.create_task(publish_later())
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        received.append(json.loads(line[5:]))
                    if len(received) == 2:
                        break
                await publisher
    assert [e["tool_name"] for e in received] == ["t__x", "t__y"]


async def test_audit_stream_requires_admin(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/audit/stream")).status_code == 401
