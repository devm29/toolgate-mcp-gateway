from __future__ import annotations

import base64
from urllib.parse import quote_plus, urlencode

import pytest
from httpx import AsyncClient

from tests.integration.oauth_helpers import (
    REDIRECT_URI,
    authorize,
    exchange,
    hidden_field,
    mcp_initialize,
    pkce,
    register_public_client,
)
from toolgate.config import CONSOLE_CLIENT_ID

pytestmark = pytest.mark.asyncio


async def _seed_users(container) -> None:
    await container.oauth.ensure_user("alice", "pw", display_name="Alice", is_admin=True)
    await container.oauth.ensure_user("bob", "pw", display_name="Bob", is_admin=False)


async def test_metadata_documents_endpoints(client: AsyncClient) -> None:
    meta = (await client.get("/.well-known/oauth-authorization-server")).json()
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["token_endpoint"].endswith("/oauth/token")
    resource = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert resource["authorization_servers"] == [meta["issuer"]]


async def test_mcp_requires_auth_with_discovery_hint(client: AsyncClient) -> None:
    response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


async def test_dynamic_registration_rejects_bad_redirect(client: AsyncClient) -> None:
    response = await client.post(
        "/oauth/register",
        json={"client_name": "x", "redirect_uris": ["javascript:alert(1)"], "grant_types": ["authorization_code"]},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


async def test_full_authorization_code_pkce_flow(client: AsyncClient, container) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client)
    grant = await authorize(client, client_id)
    token = await exchange(client, grant)
    assert token.status_code == 200
    body = token.json()
    assert body["token_type"] == "Bearer"
    assert "refresh_token" in body
    assert token.headers["cache-control"] == "no-store"
    assert (await mcp_initialize(client, body["access_token"])).status_code == 200


async def test_code_replay_revokes_refresh_and_access_tokens(client: AsyncClient, container) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client)
    grant = await authorize(client, client_id)
    body = (await exchange(client, grant)).json()
    assert (await mcp_initialize(client, body["access_token"])).status_code == 200

    replay = await exchange(client, grant)
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"

    # Everything the leaked code produced is dead, including the access token still inside its lifetime.
    revoked = await mcp_initialize(client, body["access_token"])
    assert revoked.status_code == 401
    assert "revoked" in revoked.json()["error_description"]
    refreshed = await client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": client_id},
    )
    assert refreshed.status_code == 400


async def test_refresh_rotation_and_reuse_detection(client: AsyncClient, container) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client)
    first = (await exchange(client, await authorize(client, client_id))).json()

    rotated = await client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": client_id},
    )
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert (await mcp_initialize(client, second["access_token"])).status_code == 200

    # Presenting the already-rotated token again means two parties hold the family: all of it dies.
    reused = await client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": client_id},
    )
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"
    latest = await client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": second["refresh_token"], "client_id": client_id},
    )
    assert latest.status_code == 400
    assert (await mcp_initialize(client, second["access_token"])).status_code == 401


async def test_refresh_cannot_widen_scope(client: AsyncClient, container) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client)
    body = (await exchange(client, await authorize(client, client_id, scope="mcp:tools.list"))).json()
    widened = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": body["refresh_token"],
            "client_id": client_id,
            "scope": "mcp:tools.list mcp:tools.call",
        },
    )
    assert widened.status_code == 400
    assert widened.json()["error"] == "invalid_scope"


async def test_revocation_endpoint_kills_access_token(client: AsyncClient, container) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client)
    body = (await exchange(client, await authorize(client, client_id))).json()
    revoke = await client.post("/oauth/revoke", data={"token": body["access_token"], "client_id": client_id})
    assert revoke.status_code == 200
    assert (await mcp_initialize(client, body["access_token"])).status_code == 401


async def test_revoking_refresh_token_kills_family(client: AsyncClient, container) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client)
    body = (await exchange(client, await authorize(client, client_id))).json()
    await client.post("/oauth/revoke", data={"token": body["refresh_token"], "client_id": client_id})
    refreshed = await client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": client_id},
    )
    assert refreshed.status_code == 400
    assert (await mcp_initialize(client, body["access_token"])).status_code == 401


async def test_mcp_rejects_insufficient_scope(client: AsyncClient, container, settings) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client, scope="mcp:tools.list mcp:tools.call toolgate:admin")
    grant = await authorize(client, client_id, scope="toolgate:admin", resource=settings.admin_resource)
    admin_token = (await exchange(client, grant)).json()["access_token"]
    # An admin-API token is bound to the /api audience, so the MCP resource refuses it outright.
    response = await mcp_initialize(client, admin_token)
    assert response.status_code == 401
    assert "different resource" in response.json()["error_description"]


async def test_mcp_scope_challenge_for_token_without_mcp_scopes(client: AsyncClient, container, settings) -> None:
    issued = container.tokens.issue(
        subject="user:alice", client_id="tg_x", scopes=["toolgate:admin"], resource=settings.mcp_resource
    )
    response = await mcp_initialize(client, issued.token)
    assert response.status_code == 403
    challenge = response.headers["www-authenticate"]
    assert 'error="insufficient_scope"' in challenge
    assert "mcp:tools.call" in challenge


async def test_mcp_rejects_foreign_audience(client: AsyncClient, container) -> None:
    issued = container.tokens.issue(
        subject="user:alice", client_id="tg_x", scopes=["mcp:tools.call"], resource="https://elsewhere.example/mcp"
    )
    response = await mcp_initialize(client, issued.token)
    assert response.status_code == 401


async def test_authorize_rejects_plain_pkce(client: AsyncClient, container) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client)
    _, challenge = pkce()
    page = await client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "plain",
        },
    )
    assert page.status_code == 303
    assert "error=invalid_request" in page.headers["location"]


async def test_login_requires_csrf_token_and_pages_refuse_framing(client: AsyncClient, container) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client)
    _, challenge = pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    page = await client.get("/oauth/authorize", params=params)
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    return_to = f"/oauth/authorize?{urlencode(params)}"

    forged = await client.post(
        "/oauth/login", data={"username": "alice", "password": "pw", "return_to": return_to, "csrf": "forged"}
    )
    assert forged.status_code == 403
    client.cookies.clear()
    missing_cookie = await client.post(
        "/oauth/login",
        data={
            "username": "alice",
            "password": "pw",
            "return_to": return_to,
            "csrf": hidden_field(page.text, "csrf"),
        },
    )
    assert missing_cookie.status_code == 403


async def test_non_admin_cannot_obtain_admin_scope(client: AsyncClient, container, settings) -> None:
    await _seed_users(container)
    client_id = await register_public_client(client, scope="toolgate:admin")
    _, challenge = pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "toolgate:admin",
        "resource": settings.admin_resource,
    }
    page = await client.get("/oauth/authorize", params=params)
    signed_in = await client.post(
        "/oauth/login",
        data={
            "username": "bob",
            "password": "pw",
            "return_to": f"/oauth/authorize?{urlencode(params)}",
            "csrf": hidden_field(page.text, "csrf"),
        },
    )
    consent = await client.get(signed_in.headers["location"])
    decision = await client.post(
        "/oauth/authorize", data={**params, "csrf": hidden_field(consent.text, "csrf"), "decision": "allow"}
    )
    assert decision.status_code == 303
    assert "error=access_denied" in decision.headers["location"]


async def test_client_credentials_grant(client: AsyncClient) -> None:
    reg = await client.post(
        "/oauth/register",
        json={
            "client_name": "machine",
            "grant_types": ["client_credentials"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    body = reg.json()
    token = await client.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": body["client_id"],
            "client_secret": body["client_secret"],
            "scope": "mcp:tools.list mcp:tools.call",
        },
    )
    assert token.status_code == 200
    assert token.json()["scope"]


async def test_basic_auth_credentials_are_form_decoded(client: AsyncClient) -> None:
    reg = await client.post(
        "/oauth/register",
        json={
            "client_name": "machine",
            "grant_types": ["client_credentials"],
            "token_endpoint_auth_method": "client_secret_basic",
        },
    )
    body = reg.json()
    raw = f"{quote_plus(body['client_id'])}:{quote_plus(body['client_secret'])}"
    token = await client.post(
        "/oauth/token",
        headers={"Authorization": f"Basic {base64.b64encode(raw.encode()).decode()}"},
        data={"grant_type": "client_credentials"},
    )
    assert token.status_code == 200


async def test_console_client_is_registered_for_admin_scope_only(container) -> None:
    console = await container.oauth.get_client(CONSOLE_CLIENT_ID)
    assert console is not None
    assert console.token_endpoint_auth_method == "none"
    assert console.scope == "toolgate:admin"
    assert console.redirect_uris == ["http://localhost:3101/api/auth/callback"]
