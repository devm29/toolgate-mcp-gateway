"""Put a running gateway into the demo state shown in the README and drive agent traffic through it.

`prepare` seeds, approves the benign tools and stages the rug pull; `traffic` replays a scripted mix of
allowed and blocked calls. Both need the API up (`make dev-api`). Seeding rotates the demo agent's secret.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from toolgate.config import get_settings
from toolgate.seed import seed

PASSWORD = "toolgate-demo"
REDIRECT_URI = "http://localhost:4000/callback"
SCOPE = "mcp:tools.list mcp:tools.call"
PROTOCOL_VERSION = "2025-06-18"
MCP_ACCEPT = "application/json, text/event-stream"

ADMIN_SCOPE = "toolgate:admin"
RUG_PULL_TOOL = "notes__summarize_release"
BENIGN_TOOLS = (
    "weather__get_forecast",
    "weather__get_alerts",
    "github__list_issues",
    "github__create_issue",
    "github__delete_branch",
    "files__read_file",
    "files__list_directory",
    "crm__lookup_customer",
    "crm__create_ticket",
    "mailer__send_email",
    "mailer__list_inbox",
)

Call = tuple[str, str, dict[str, Any]]

# (caller, tool, arguments). Callers: "alice" and "ops" are users, "agent" is the demo client_credentials client.
SCRIPT: list[Call] = [
    ("agent", "weather__get_forecast", {"city": "Lisbon"}),
    ("alice", "github__list_issues", {"repo": "acme/payments"}),
    ("agent", "crm__lookup_customer", {"email": "dana@example.com"}),
    ("alice", "github__create_issue", {"repo": "acme/payments", "title": "Refund webhook retries twice"}),
    ("ops", "files__read_file", {"path": "/workspace/README.md"}),
    ("ops", "files__read_file", {"path": "/home/ops/.ssh/id_rsa"}),
    ("agent", "weather__get_alerts", {"region": "TX"}),
    ("alice", "github__delete_branch", {"repo": "acme/payments", "branch": "main"}),
    ("agent", "github__create_issue", {"repo": "acme/payments", "title": "Automated triage"}),
    ("alice", "github__create_issue", {"repo": "evil/fork", "title": "Mirror secrets"}),
    ("agent", "github__list_issues", {"repo": "acme/payments", "token": "ghp_exfil"}),
    ("alice", "mailer__send_email", {"to": "oncall@acme.dev", "subject": "Deploy finished", "body": "v2.14.0 is live"}),
    ("agent", "mailer__send_email", {"to": "attacker@evil.example", "subject": "hi", "body": "x"}),
    ("agent", "mathtools__add", {"a": 2, "b": 3}),
    ("alice", "notes__summarize_release", {"version": "2.14.0"}),
    ("agent", "translator__translate", {"text": "hello", "target": "fr"}),
    ("ops", "files__list_directory", {"path": "/workspace"}),
    ("agent", "weather__get_forecast", {"city": "Tokyo"}),
    ("alice", "github__list_issues", {"repo": "acme/web"}),
    ("ops", "files__read_file", {"path": "/workspace/docs/runbook.md"}),
    ("agent", "crm__lookup_customer", {"email": "lee@example.com"}),
    ("ops", "files__read_file", {"path": "/etc/passwd"}),
]


@dataclass(frozen=True, slots=True)
class Outcome:
    tool: str
    caller: str
    ok: bool


def _hidden_field(html: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', html)
    if match is None:
        raise RuntimeError(f"sign-in page has no {name} field")
    return match.group(1).replace("&amp;", "&")


def _expect(response: httpx.Response, status: int) -> httpx.Response:
    if response.status_code != status:
        request = response.request
        raise RuntimeError(f"{request.method} {request.url.path}: {response.status_code} {response.text}")
    return response


async def user_token(base_url: str, username: str, *, scope: str = SCOPE, resource: str | None = None) -> str:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as http:
        registered = _expect(
            await http.post(
                "/oauth/register",
                json={
                    "client_name": "Demo traffic",
                    "redirect_uris": [REDIRECT_URI],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "token_endpoint_auth_method": "none",
                    "scope": scope,
                },
            ),
            201,
        )
        client_id: str = registered.json()["client_id"]
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": scope,
            "state": secrets.token_urlsafe(8),
        }
        if resource:
            params["resource"] = resource
        page = _expect(await http.get(f"/oauth/authorize?{urlencode(params)}"), 200)
        signed_in = _expect(
            await http.post(
                "/oauth/login",
                data={
                    "username": username,
                    "password": PASSWORD,
                    "return_to": _hidden_field(page.text, "return_to"),
                    "csrf": _hidden_field(page.text, "csrf"),
                },
            ),
            303,
        )
        consent = _expect(await http.get(signed_in.headers["location"]), 200)
        decision = _expect(
            await http.post(
                "/oauth/authorize", data={**params, "csrf": _hidden_field(consent.text, "csrf"), "decision": "allow"}
            ),
            303,
        )
        code = parse_qs(urlparse(decision.headers["location"]).query)["code"][0]
        token = _expect(
            await http.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    **({"resource": resource} if resource else {}),
                },
            ),
            200,
        )
        access_token: str = token.json()["access_token"]
        return access_token


async def client_token(base_url: str, client_id: str, client_secret: str) -> str:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as http:
        response = _expect(
            await http.post(
                "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": SCOPE,
                },
            ),
            200,
        )
        access_token: str = response.json()["access_token"]
        return access_token


class McpSession:
    def __init__(self, base_url: str, token: str) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=60,
            headers={"Authorization": f"Bearer {token}", "Accept": MCP_ACCEPT},
        )
        self._next_id = 0

    async def _send(self, method: str, params: dict[str, Any] | None = None, *, notify: bool = False) -> httpx.Response:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._next_id += 1
            body["id"] = self._next_id
        response = await self._http.post("/mcp", json=body)
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._http.headers["Mcp-Session-Id"] = session_id
        return response

    async def initialize(self) -> None:
        response = await self._send(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "demo-agent", "version": "1"},
            },
        )
        _expect(response, 200)
        self._http.headers["Mcp-Protocol-Version"] = PROTOCOL_VERSION
        await self._send("notifications/initialized", notify=True)

    async def call(self, tool: str, arguments: dict[str, Any]) -> bool:
        response = await self._send("tools/call", {"name": tool, "arguments": arguments})
        return response.status_code == 200 and '"isError":true' not in response.text

    async def close(self) -> None:
        await self._http.aclose()


async def _approve(admin: httpx.AsyncClient, tool_id: str, note: str) -> dict[str, Any]:
    detail: dict[str, Any] = _expect(await admin.get(f"/api/v1/tools/{tool_id}"), 200).json()
    response = await admin.post(
        f"/api/v1/tools/{tool_id}/approve", json={"expected_hash": detail["current_hash"], "note": note}
    )
    approved: dict[str, Any] = _expect(response, 200).json()
    return approved


async def _tools(admin: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    page = _expect(await admin.get("/api/v1/tools", params={"limit": 200}), 200).json()
    return {tool["exposed_name"]: tool for tool in page["items"]}


async def _set_rug_pull_after(admin: httpx.AsyncClient, upstream_id: str, lists: int) -> None:
    patch = {"env": {"RUG_PULL_AFTER_LISTS": str(lists)}}
    _expect(await admin.patch(f"/api/v1/upstreams/{upstream_id}", json=patch), 200)
    _expect(await admin.post(f"/api/v1/upstreams/{upstream_id}/sync"), 200)


async def _stage_rug_pull(admin: httpx.AsyncClient) -> str:
    upstreams = {u["name"]: u for u in _expect(await admin.get("/api/v1/upstreams"), 200).json()}
    upstream_id = upstreams["notes"]["id"]
    tool = (await _tools(admin)).get(RUG_PULL_TOOL)
    if tool is not None and tool["status"] == "quarantined" and tool["has_drift"]:
        return "already staged"
    # The fixture switches definitions after RUG_PULL_AFTER_LISTS listings; changing its env restarts it.
    await _set_rug_pull_after(admin, upstream_id, 1_000_000)
    tool = (await _tools(admin))[RUG_PULL_TOOL]
    if tool["status"] != "approved":
        await _approve(admin, tool["id"], "Benign summary tool")
    await _set_rug_pull_after(admin, upstream_id, 0)
    status: str = (await _tools(admin))[RUG_PULL_TOOL]["status"]
    return status


async def prepare(base_url: str, admin_resource: str) -> None:
    token = await user_token(base_url, "alice", scope=ADMIN_SCOPE, resource=admin_resource)
    async with httpx.AsyncClient(base_url=base_url, timeout=60, headers={"Authorization": f"Bearer {token}"}) as admin:
        # Upstreams seeded while the API was running are only connected once something syncs them.
        for upstream in _expect(await admin.get("/api/v1/upstreams"), 200).json():
            if upstream["enabled"]:
                _expect(await admin.post(f"/api/v1/upstreams/{upstream['id']}/sync"), 200)
        tools = await _tools(admin)
        approved = 0
        for name in BENIGN_TOOLS:
            tool = tools.get(name)
            if tool is not None and tool["status"] == "pending":
                await _approve(admin, tool["id"], "Reviewed definition and scan report")
                approved += 1
        print(f"approved {approved} benign tools; rug pull: {await _stage_rug_pull(admin)}")


async def traffic(base_url: str, client_id: str, client_secret: str, *, rounds: int, delay: float, burst: int) -> None:
    tokens = {
        "alice": await user_token(base_url, "alice"),
        "ops": await user_token(base_url, "ops"),
        "agent": await client_token(base_url, client_id, client_secret),
    }
    sessions = {caller: McpSession(base_url, token) for caller, token in tokens.items()}
    outcomes: list[Outcome] = []
    try:
        for session in sessions.values():
            await session.initialize()
        for _ in range(rounds):
            for caller, tool, arguments in SCRIPT:
                outcomes.append(Outcome(tool, caller, await sessions[caller].call(tool, arguments)))
                await asyncio.sleep(delay)
        # Trips the token bucket on CRM lookups so the log shows rate limiting.
        for index in range(burst):
            ok = await sessions["agent"].call("crm__lookup_customer", {"email": f"user{index}@example.com"})
            outcomes.append(Outcome("crm__lookup_customer", "agent", ok))
    finally:
        for session in sessions.values():
            await session.close()
    passed = sum(outcome.ok for outcome in outcomes)
    print(f"{len(outcomes)} calls sent, {passed} succeeded, {len(outcomes) - passed} blocked or failed")


async def _amain(args: argparse.Namespace) -> None:
    settings = get_settings()
    demo = await seed(settings)
    if args.command == "prepare":
        await prepare(settings.issuer, settings.admin_resource)
    else:
        await traffic(
            settings.issuer,
            demo.client_id,
            demo.client_secret,
            rounds=args.rounds,
            delay=args.delay,
            burst=args.burst,
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m fixtures.demo", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare", help="Seed, approve the benign tools and stage the rug pull")
    traffic_parser = sub.add_parser("traffic", help="Send scripted MCP calls as alice, ops and the demo agent")
    traffic_parser.add_argument("--rounds", type=int, default=1, help="Times to replay the scripted calls")
    traffic_parser.add_argument("--delay", type=float, default=0.15, help="Seconds between calls")
    traffic_parser.add_argument("--burst", type=int, default=0, help="Extra CRM lookups sent back to back")
    asyncio.run(_amain(parser.parse_args()))


if __name__ == "__main__":
    main()
