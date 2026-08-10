from __future__ import annotations

import sys
from dataclasses import dataclass

from sqlalchemy import delete, select

from toolgate.auth.models import OAuthClient
from toolgate.auth.passwords import hash_token, new_token
from toolgate.config import Settings, get_settings
from toolgate.container import Container, build_container
from toolgate.logging import configure_logging, get_logger
from toolgate.policy.models import PolicyRecord
from toolgate.policy.schemas import PolicyCreate, PolicyRule, RateLimit
from toolgate.registry.models import Transport
from toolgate.registry.schemas import UpstreamCreate

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DemoClient:
    client_id: str
    client_secret: str


def _fixture_command(module: str) -> tuple[str, list[str]]:
    return sys.executable, ["-m", f"fixtures.servers.{module}", "--transport", "stdio"]


def _upstreams(settings: Settings) -> list[UpstreamCreate]:
    def stdio(name: str, display: str, module: str, description: str) -> UpstreamCreate:
        command, args = _fixture_command(module)
        return UpstreamCreate(
            name=name,
            display_name=display,
            description=description,
            transport=Transport.STDIO,
            command=command,
            args=args,
        )

    specs = [
        stdio("weather", "Weather API", "weather", "Forecasts and severe-weather alerts."),
        stdio("github", "GitHub", "github", "Issues and branches for the payments service."),
        stdio("mailer", "Mailer", "mailer", "Transactional email from the team mailbox."),
        stdio("files", "Workspace files", "files", "Read-only access to the deploy workspace."),
        stdio("mathtools", "Math tools", "poisoned", "Community math helper (red-team: tool poisoning)."),
        stdio("notes", "Release notes", "rug_pull", "Release-note summaries (red-team: rug pull)."),
        stdio("mailhelper", "Mail helper", "shadowing", "Email signature helper (red-team: shadowing)."),
        stdio("translator", "Translator", "unicode_smuggling", "Translation helper (red-team: unicode smuggling)."),
    ]
    crm = UpstreamCreate(
        name="crm",
        display_name="CRM (HTTP)",
        description="Customer lookups over Streamable HTTP.",
        transport=Transport.STREAMABLE_HTTP,
        url=f"{settings.issuer}/fixtures/crm/mcp",  # type: ignore[arg-type]
    )
    return [*specs, crm]


def _policies() -> list[PolicyCreate]:
    return [
        PolicyCreate(
            name="baseline-allow",
            description="Everyone may list and call approved read-only style tools, with a fleet-wide rate limit.",
            rules=[
                PolicyRule(
                    id="allow-weather",
                    effect="allow",
                    tools=["weather__*", "translator__*"],
                    rate_limit=RateLimit(capacity=30, refill_per_minute=60),
                    description="Low-risk informational tools",
                ),
                PolicyRule(
                    id="allow-github-read",
                    effect="allow",
                    tools=["github__list_issues", "crm__lookup_customer", "files__*"],
                    rate_limit=RateLimit(capacity=20, refill_per_minute=30),
                ),
            ],
        ),
        PolicyCreate(
            name="writes-restricted",
            description="Writes are limited to the ops team and shaped by argument constraints.",
            rules=[
                PolicyRule(
                    id="allow-issue-create",
                    effect="allow",
                    principals=["user:alice", "user:ops"],
                    tools=["github__create_issue"],
                    arguments={
                        "type": "object",
                        "properties": {"repo": {"enum": ["acme/payments", "acme/web"]}},
                        "required": ["repo"],
                    },
                    rate_limit=RateLimit(capacity=5, refill_per_minute=10),
                    description="Only known repositories",
                ),
                PolicyRule(
                    id="deny-branch-delete",
                    effect="deny",
                    tools=["github__delete_branch"],
                    description="Branch deletion is never allowed through the gateway",
                ),
                # Principal globs are matched against every identity on a token, including client:<id>.
                # A client:* grant would therefore hand this tool to any user of any registered client.
                PolicyRule(
                    id="allow-email-ops",
                    effect="allow",
                    principals=["user:alice", "user:ops"],
                    tools=["mailer__send_email"],
                    rate_limit=RateLimit(capacity=3, refill_per_minute=6),
                ),
            ],
        ),
        PolicyCreate(
            name="protect-secrets",
            description="Block reads of credential and system files even if a tool is approved.",
            rules=[
                PolicyRule(
                    id="deny-secret-files",
                    effect="deny",
                    tools=["files__read_file"],
                    arguments={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "pattern": "(\\.ssh/|/etc/|credentials|id_rsa|\\.env)"}
                        },
                        "required": ["path"],
                    },
                    description="Paths that look like secrets are off limits",
                ),
            ],
        ),
    ]


async def seed(settings: Settings, *, reset: bool = False) -> DemoClient:
    container = await build_container(settings)
    try:
        await container.oauth.ensure_user("alice", "toolgate-demo", display_name="Alice Nguyen (admin)", is_admin=True)
        await container.oauth.ensure_user("ops", "toolgate-demo", display_name="Ops Bot", is_admin=False)

        if reset:
            await _reset(container)
        existing = {u.name: u for u in await container.registry.upstream_models()}

        for spec in _upstreams(settings):
            if spec.name not in existing:
                await container.registry.create_upstream(spec)

        async with container.sessions() as session:
            if not (await session.scalars(select(PolicyRecord).limit(1))).first():
                for policy in _policies():
                    await container.policies.create(policy)

        client = await _demo_client(container)
        log.info("seed_complete", client_id=client.client_id)
        return client
    finally:
        await container.close()


async def _reset(container: Container) -> None:
    from toolgate.registry.models import Upstream

    async with container.sessions() as session, session.begin():
        await session.execute(delete(PolicyRecord))
        await session.execute(delete(Upstream))


async def _demo_client(container: Container) -> DemoClient:
    secret = new_token()
    async with container.sessions() as session, session.begin():
        row = await session.scalar(select(OAuthClient).where(OAuthClient.client_name == "Toolgate demo agent"))
        if row is None:
            row = OAuthClient(
                client_id=f"tg_{new_token(8)}",
                client_name="Toolgate demo agent",
                token_endpoint_auth_method="client_secret_post",
                grant_types=["client_credentials"],
                redirect_uris=[],
                scope="mcp:tools.list mcp:tools.call",
            )
            session.add(row)
        row.client_secret_hash = hash_token(secret)
    return DemoClient(client_id=row.client_id, client_secret=secret)


async def _amain(*, reset: bool = False) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    result = await seed(settings, reset=reset)
    print(f"Demo agent client_id:     {result.client_id}")
    print(f"Demo agent client_secret: {result.client_secret}")
    print("Console admin login:      alice / toolgate-demo")
