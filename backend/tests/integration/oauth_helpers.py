from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from httpx import AsyncClient, Response

REDIRECT_URI = "http://localhost:4000/callback"
MCP_ACCEPT = "application/json, text/event-stream"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def hidden_field(html: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', html)
    assert match is not None, f"no hidden field {name}"
    return match.group(1)


async def register_public_client(client: AsyncClient, *, scope: str | None = None) -> str:
    body: dict[str, Any] = {
        "client_name": "Test agent",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
    }
    if scope:
        body["scope"] = scope
    response = await client.post("/oauth/register", json=body)
    assert response.status_code == 201, response.text
    client_id: str = response.json()["client_id"]
    return client_id


async def login(client: AsyncClient, return_to: str, *, username: str, password: str) -> Response:
    page = await client.get(return_to)
    assert page.status_code == 200 and "Sign in" in page.text
    return await client.post(
        "/oauth/login",
        data={
            "username": username,
            "password": password,
            "return_to": hidden_field(page.text, "return_to").replace("&amp;", "&"),
            "csrf": hidden_field(page.text, "csrf"),
        },
    )


@dataclass
class Grant:
    code: str
    verifier: str
    client_id: str
    redirect_uri: str = REDIRECT_URI


async def authorize(
    client: AsyncClient,
    client_id: str,
    *,
    username: str = "alice",
    password: str = "pw",
    scope: str = "mcp:tools.list mcp:tools.call",
    resource: str | None = None,
    redirect_uri: str = REDIRECT_URI,
) -> Grant:
    verifier, challenge = pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": scope,
        "state": "xyz",
    }
    if resource:
        params["resource"] = resource
    return_to = f"/oauth/authorize?{urlencode(params)}"
    signed_in = await login(client, return_to, username=username, password=password)
    assert signed_in.status_code == 303, signed_in.text
    consent = await client.get(signed_in.headers["location"])
    assert consent.status_code == 200, consent.text
    decision = await client.post(
        "/oauth/authorize", data={**params, "csrf": hidden_field(consent.text, "csrf"), "decision": "allow"}
    )
    assert decision.status_code == 303, decision.text
    query = parse_qs(urlparse(decision.headers["location"]).query)
    assert query["state"] == ["xyz"]
    assert "code" in query, query
    return Grant(code=query["code"][0], verifier=verifier, client_id=client_id, redirect_uri=redirect_uri)


async def exchange(client: AsyncClient, grant: Grant, *, resource: str | None = None) -> Response:
    data = {
        "grant_type": "authorization_code",
        "code": grant.code,
        "redirect_uri": grant.redirect_uri,
        "client_id": grant.client_id,
        "code_verifier": grant.verifier,
    }
    if resource:
        data["resource"] = resource
    return await client.post("/oauth/token", data=data)


async def mcp_initialize(client: AsyncClient, token: str) -> Response:
    return await client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}", "Accept": MCP_ACCEPT},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )
