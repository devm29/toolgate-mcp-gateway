<div align="center">

# Toolgate

### A zero-trust gateway and tool registry for the Model Context Protocol

Put every MCP server behind one authenticated endpoint. Treat tool descriptions as untrusted input.<br/>
Catch tool poisoning and silent "rug-pull" definition changes before an agent reads them.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](backend/src/toolgate/app.py)
[![MCP SDK](https://img.shields.io/badge/MCP-Streamable%20HTTP%20%2B%20stdio-111111)](backend/src/toolgate/federation)
[![OAuth 2.1](https://img.shields.io/badge/OAuth%202.1-PKCE%20%C2%B7%20DCR%20%C2%B7%20RFC%209728-EB5424)](backend/src/toolgate/auth)
[![Next.js 15](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)](web/package.json)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](docker-compose.yml)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](docker-compose.yml)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-GenAI%20spans-425CC7?logo=opentelemetry&logoColor=white)](backend/src/toolgate/audit/telemetry.py)
[![mypy strict](https://img.shields.io/badge/mypy-strict-2A6DB2)](backend/pyproject.toml)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Why](#why-this-exists) · [Features](#what-it-does) · [Attacks blocked](#attacks-blocked) · [Architecture](#architecture) · [Quickstart](#quickstart) · [API](#api-overview) · [Testing](#testing)

<br/>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/overview-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/screenshots/overview-light.png">
  <img alt="Toolgate console overview: upstream servers, exposed tools, approval queue, 24-hour call volume and risk distribution" src="docs/screenshots/overview-light.png" width="100%">
</picture>

</div>

---

## Why this exists

An MCP tool's name, description and input schema go straight into the model's context. The model reads that
text as instructions. So anyone who controls an MCP server can steer an agent, without touching the user's
prompt or the agent's code:

- **Tool poisoning.** A description hides an `<IMPORTANT>` block that tells the model to read `~/.ssh/id_rsa`
  and pass it in a "sidenote" argument.
- **Rug pulls.** A server ships a clean definition, waits until it is approved, then swaps the text.
  Most clients never notice, because they re-read `tools/list` on every session.
- **Shadowing.** One server's description rewrites how the model should use *another* server's `send_email`.
- **Unicode smuggling.** Invisible Unicode tag characters carry instructions that no human reviewer can see.

Toolgate sits between agents and upstream MCP servers. Every definition is scanned, reviewed by a person and
pinned by SHA-256. Agents only ever see the pinned version. Every call passes identity, pin, schema, policy and
rate-limit checks, and lands in an append-only audit log.

## What it does

| | Capability | Details |
| :-: | --- | --- |
| **1** | **Federation** | One supervised MCP client session per upstream, over stdio or Streamable HTTP. Tools are exposed as `server__tool`. Names are sanitized to `[A-Za-z0-9_-]{1,64}`, and a short hash suffix settles collisions. `tools/list` merges every approved tool the caller's policies allow. Dead sessions are reconnected with jittered backoff. `tools/list_changed` triggers an immediate re-sync. |
| **2** | **OAuth 2.1 authorization server** | Authorization code with PKCE (S256 only), dynamic client registration (RFC 7591), protected resource metadata (RFC 9728), `iss` in the authorization response (RFC 9207) and audience-bound RS256 JWT access tokens (RFC 9068) that last 10 minutes. Refresh tokens rotate, and reuse is detected. A replayed authorization code revokes everything issued from it. Upstreams never see user credentials. |
| **3** | **Tool-poisoning scanner** | A pure rules pipeline: hidden instructions, Unicode tag, zero-width and bidi smuggling, cross-tool shadowing, exfiltration URLs and emails, and oversized schemas. It walks every string in the definition, including property names, annotations and nested schema keywords. The result is a typed `ScanReport` with a 0 to 100 score. An optional LLM classifier sits behind a `ToolClassifier` protocol, with a deterministic offline version and an Anthropic version. |
| **4** | **Description pinning** | Name, title, description, input and output schemas and annotations are canonicalized as JSON (sorted keys, ASCII escapes, no Unicode normalization) and hashed with SHA-256. Any drift quarantines the tool until an admin approves the change from a side-by-side diff. |
| **5** | **Policies** | Pydantic-validated allow and deny rules, matched by principal glob and tool glob. Deny wins over allow, and anything not allowed is denied. Rules can carry JSON Schema argument constraints and Redis token-bucket rate limits. They are enforced on every `tools/call`, and a simulator in the console shows the result before you save. |
| **6** | **Audit** | An append-only Postgres table holds every call: redacted arguments, decision, reason, latency, upstream and trace id. Calls stream live over SSE, fanned out through Redis pub/sub and replayed with `Last-Event-ID`. Each call is also an OpenTelemetry `execute_tool` span with GenAI semantic attributes. |
| **7** | **Admin console** | Next.js 15 screens for the server registry, the tool inventory with risk scores, the approval queue with a diff that shows invisible code points, the policy editor and simulator, and a live and historical call stream. |
| **8** | **Red-team suite** | Bundled malicious MCP servers run through the real gateway, and pytest asserts that each attack is blocked. `make attack-report` writes the table below. |

## Attacks blocked

Generated by `make attack-report` from [`backend/tests/redteam`](backend/tests/redteam) and written to
[`docs/attack-blocked.json`](docs/attack-blocked.json). Every fixture payload is an inert, labelled canary.

| Attack | Technique | Fixture | Outcome |
| --- | --- | --- | --- |
| Tool poisoning | Hidden `<IMPORTANT>` block steering the model toward secret files | [`poisoned.py`](backend/fixtures/servers/poisoned.py) | Scored critical (100), held for review, call blocked |
| Rug pull | Definition swapped after approval | [`rug_pull.py`](backend/fixtures/servers/rug_pull.py) | SHA-256 pin mismatch, re-quarantined, call blocked |
| Live rug pull | Definition changed mid-session and announced with `tools/list_changed` | [`hot_swap.py`](backend/fixtures/servers/hot_swap.py) | Re-synced at once and quarantined, no polling interval involved |
| Cross-tool shadowing | Tool claims authority over another server's `send_email` | [`shadowing.py`](backend/fixtures/servers/shadowing.py) | Shadowing rule fires (critical), held for review |
| Unicode smuggling | Invisible Unicode tag characters encode hidden text | [`unicode_smuggling.py`](backend/fixtures/servers/unicode_smuggling.py) | Payload decoded and flagged (critical), held for review |
| Credential file read | Approved file tool asked for `~/.ssh/id_rsa` | [`files.py`](backend/fixtures/servers/files.py) | Deny rule matches the argument, call blocked and audited |
| Argument injection | Extra argument smuggled into a `tools/call` | [`github.py`](backend/fixtures/servers/github.py) | Rejected against the pinned schema before the upstream is called |

## Screenshots

**Approval queue.** New tools and post-approval changes, with the top scanner findings for each.

![Approval queue with a quarantined rug-pull change and scanner findings](docs/screenshots/approvals-light.png)

**Rug-pull diff.** The approved pin next to what the upstream serves now, with invisible characters shown as markers.

![Side-by-side diff of an approved and changed tool description](docs/screenshots/rugpull-diff-dark.png)

**Scan report.** Typed findings with location, rule and evidence, plus the classifier's verdict.

![Scan report for a poisoned tool with three findings](docs/screenshots/scan-findings-light.png)

**Policies and simulator.** Allow and deny rules with argument constraints and rate limits; the simulator shows `protect-secrets` blocking an SSH key read.

![Policies list with a simulator denying a read of an SSH key](docs/screenshots/policies-dark.png)

**Live activity.** SSE stream of every call with its decision, principal and latency.

![Live activity feed of tool calls with decisions](docs/screenshots/activity-light.png)

**Audit history.** Cursor-paginated Postgres history, filterable by tool, principal and decision, with each row expanding to its policy reason, trace id and redacted arguments.

![Audit history with an expanded denied call showing the reason and redacted arguments](docs/screenshots/activity-history-dark.png)

**Tool inventory.** Every discovered tool with its status, risk score and drift flag.

![Tool inventory with status, risk score and findings](docs/screenshots/tools-dark.png)

**Policy editor.** A structured form or raw JSON, validated by the same Pydantic models as the API.

![Policy editor form with rule fields](docs/screenshots/policy-editor-light.png)

**Server registry.** stdio and Streamable HTTP upstreams with health and per-status tool counts.

![Upstream server registry](docs/screenshots/servers-light.png)

**OAuth consent.** The console signs admins in through Toolgate's own authorization server.

![Toolgate OAuth consent page](docs/screenshots/oauth-consent.png)

## Architecture

### System overview

```mermaid
flowchart TB
    AG["MCP agent<br/>(Claude, IDE, script)"]
    ADM["Admin browser"]

    subgraph Console["web/ - Next.js 15 console"]
        UI["Console UI<br/>TanStack Query"] --> BFF["Route handlers<br/>sealed session cookie"]
    end

    subgraph Gateway["backend/ - FastAPI gateway"]
        direction TB
        AUTH["auth<br/>OAuth 2.1 AS + JWKS"]
        MCP["/mcp<br/>Streamable HTTP + bearer check"]
        ADMINAPI["/api/v1<br/>admin REST + SSE"]
        GW["GatewayService<br/>tools/call pipeline"]
        REG["registry<br/>upstreams, tools, pins"]
        SCAN["scanner<br/>rules + classifier"]
        POL["policy<br/>evaluator + token bucket"]
        POOL["federation<br/>session pool + sync"]
        AUD["audit<br/>log, SSE, OTel spans"]
        MCP --> GW
        GW --> REG
        GW --> POL
        GW --> POOL
        GW --> AUD
        REG --> SCAN
        POOL -- "tools/list" --> REG
        ADMINAPI --> REG
        ADMINAPI --> POL
        ADMINAPI --> AUD
    end

    subgraph Upstreams["Upstream MCP servers"]
        U1["stdio processes"]
        U2["Streamable HTTP servers"]
    end

    PG[("PostgreSQL<br/>registry, policies, audit, OAuth")]
    RD[("Redis<br/>rate limits, audit pub/sub")]
    OT["OTLP collector"]

    AG -- "DCR + code/PKCE" --> AUTH
    AG -- "Bearer JWT" --> MCP
    ADM --> UI
    ADM -- "sign in" --> AUTH
    BFF -- "admin JWT" --> ADMINAPI
    POOL --> U1
    POOL --> U2
    REG & POL & AUD & AUTH --> PG
    POL & AUD --> RD
    AUD --> OT
```

Routes call services, and services call repositories. One `Container` builds every service at startup and is
injected through FastAPI dependencies. Settings are `pydantic-settings` models, and every error is an RFC 7807
problem document.

### The `tools/call` pipeline

Each check fails closed. A call reaches the upstream only after all of them pass.

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent
    participant M as /mcp endpoint
    participant G as GatewayService
    participant R as Registry
    participant P as Policy + Redis
    participant U as Upstream session
    participant L as Audit (Postgres, SSE, OTel)

    A->>M: tools/call github__create_issue (Bearer JWT)
    M->>M: Verify signature, issuer, audience, expiry
    alt token invalid or wrong audience
        M-->>A: 401 + WWW-Authenticate resource_metadata
    end
    M->>G: call_tool(principal, name, args)
    G->>G: Require scope mcp:tools.call
    G->>R: find_exposed(name)
    R-->>G: tool with approved_hash and current_hash
    alt status quarantined or hashes differ
        G-->>A: isError result, decision quarantined
    end
    G->>G: Validate args against the pinned input schema
    G->>P: Evaluate rules (deny wins, default deny)
    P->>P: Token bucket per rule and principal (Lua, atomic)
    alt denied or rate limited
        G-->>A: isError result with the reason
    end
    G->>U: call_tool(upstream_tool_name, args, timeout)
    U-->>G: result
    G->>G: Scan output text for injection markers
    G->>L: Append event (redacted args, decision, latency, trace id)
    L-->>L: Publish to Redis, end execute_tool span
    G-->>A: Result, output findings in _meta
```

### Rug-pull detection

```mermaid
sequenceDiagram
    autonumber
    participant U as Upstream
    participant S as SyncService
    participant R as RegistryService
    participant SC as Scanner
    participant Q as Approval queue
    participant Adm as Admin

    U->>S: tools/list_changed (or periodic refresh)
    S->>U: tools/list
    U-->>S: definitions
    S->>R: reconcile(upstream, definitions)
    R->>R: Canonical JSON, SHA-256
    alt new tool
        R->>SC: scan
        SC-->>R: ScanReport (score, findings)
        R->>Q: pending, change kind new
    else hash differs from the approved pin
        R->>SC: re-scan the new text
        R->>R: status quarantined, record ToolChange
        R->>Q: change kind changed, with both definitions
    else hash matches the pin again
        R->>R: Back to approved, change marked reverted
    end
    Adm->>Q: Open the side-by-side diff
    Adm->>R: approve(expected_hash) or reject
    R->>R: New ToolPin, or drop the live pin on reject
```

### Tool lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending: discovered by tools/list
    pending --> approved: admin approves (pin created)
    pending --> rejected: admin rejects
    pending --> pending: definition changes before review
    approved --> quarantined: upstream hash differs from pin
    quarantined --> approved: admin approves the new hash
    quarantined --> approved: upstream reverts to the pinned hash
    quarantined --> rejected: admin rejects (live pin dropped)
    rejected --> rejected: later changes never revive it
```

### OAuth 2.1 for agents

```mermaid
sequenceDiagram
    autonumber
    participant A as MCP client
    participant G as Toolgate
    participant B as User's browser

    A->>G: POST /mcp without a token
    G-->>A: 401, WWW-Authenticate resource_metadata
    A->>G: GET /.well-known/oauth-protected-resource/mcp
    A->>G: GET /.well-known/oauth-authorization-server
    A->>G: POST /oauth/register (RFC 7591)
    G-->>A: client_id
    A->>B: Open /oauth/authorize (code_challenge S256, resource)
    B->>G: Sign in, then consent
    G-->>B: Redirect with code, state and iss
    B-->>A: code
    A->>G: POST /oauth/token (code_verifier)
    G-->>A: RS256 JWT for aud /mcp (10 min) + rotating refresh token
    A->>G: POST /mcp with Bearer token
```

### Admin user flow

```mermaid
flowchart TD
    S["Sign in through Toolgate OAuth<br/>(alice, scope toolgate:admin)"] --> O["Overview<br/>traffic, risk, queue size"]
    O --> ADD["Servers: add an upstream<br/>(stdio command or HTTP URL)"]
    ADD --> SYNC["Toolgate connects and runs tools/list"]
    SYNC --> SCAN["Every tool is scanned and scored"]
    SCAN --> QUEUE["Approval queue"]
    QUEUE --> REV{"Review the definition<br/>and findings"}
    REV -- "approve" --> PIN["Pinned by SHA-256<br/>and visible to agents"]
    REV -- "reject" --> REJ["Rejected, never served"]
    PIN --> POLICY["Policies: who may call it,<br/>argument limits, rate limits"]
    POLICY --> SIM["Simulator: check a decision<br/>before saving"]
    SIM --> LIVE["Activity: watch calls live"]
    LIVE --> DRIFT{"Upstream changes<br/>a pinned tool?"}
    DRIFT -- "yes" --> QUAR["Quarantined, calls blocked"]
    QUAR --> QUEUE
    DRIFT -- "no" --> LIVE
```

### Data model

```mermaid
erDiagram
    UPSTREAMS ||--o{ TOOLS : exposes
    TOOLS ||--o{ TOOL_PINS : "approved as"
    TOOLS ||--o{ TOOL_CHANGES : "drift log"
    USERS ||--o{ AUTHORIZATION_CODES : grants
    OAUTH_CLIENTS ||--o{ AUTHORIZATION_CODES : requests
    OAUTH_CLIENTS ||--o{ REFRESH_TOKENS : holds

    UPSTREAMS {
        uuid id PK
        string name UK
        string transport "stdio or streamable_http"
        string command
        string url
        jsonb env "write-only secrets"
        jsonb headers "write-only secrets"
        string status
    }
    TOOLS {
        uuid id PK
        uuid upstream_id FK
        string exposed_name UK
        string status "pending approved quarantined rejected"
        string current_hash
        string approved_hash
        jsonb current_definition
        jsonb approved_definition
        int risk_score
        jsonb scan_report
    }
    TOOL_PINS {
        uuid id PK
        uuid tool_id FK
        string sha256
        jsonb definition
        string approved_by
    }
    TOOL_CHANGES {
        uuid id PK
        uuid tool_id FK
        string kind "new changed removed"
        string previous_hash
        string new_hash
        string resolution
    }
    POLICIES {
        uuid id PK
        string name UK
        jsonb rules
        int version
    }
    AUDIT_EVENTS {
        bigint id PK
        timestamptz occurred_at
        string principal
        string tool_name
        string decision
        jsonb arguments "redacted"
        float latency_ms
        string trace_id
    }
    USERS {
        uuid id PK
        string username UK
        bool is_admin
    }
    OAUTH_CLIENTS {
        uuid id PK
        string client_id UK
        jsonb redirect_uris
        jsonb grant_types
    }
    AUTHORIZATION_CODES {
        string code_hash PK
        string code_challenge
        uuid token_family
    }
    REFRESH_TOKENS {
        string token_hash PK
        uuid family_id
        timestamptz rotated_at
    }
    SIGNING_KEYS {
        string kid PK
        string algorithm
        bool active
    }
```

Authorization codes and refresh tokens are stored only as hashes. `audit_events` has triggers that refuse
`UPDATE`, `DELETE` and `TRUNCATE`.

## Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Gateway | Python 3.12+, FastAPI, Uvicorn | Async I/O for many long-lived upstream sessions, with typed request models |
| MCP | Official `mcp` Python SDK 2.x | Server side for `/mcp`, client side for stdio and Streamable HTTP upstreams |
| Models and config | Pydantic v2, pydantic-settings | One validated model shared by the API, the policy engine and the console's JSON editor |
| Auth | PyJWT (RS256), Authlib, `cryptography` | Standards-based tokens with JWKS; the authorization server logic is our own |
| Storage | PostgreSQL 17, SQLAlchemy 2.0 async, asyncpg, Alembic | JSONB for definitions and rules; migrations are checked for drift in CI |
| Rate limits and fan-out | Redis 7 (Lua token bucket, pub/sub) | Atomic limits and live audit streams that work across gateway replicas |
| Streaming | sse-starlette | Live audit feed with `Last-Event-ID` replay |
| Observability | OpenTelemetry SDK + OTLP exporter, structlog | GenAI `execute_tool` spans; JSON logs in production |
| Validation | `jsonschema` (Draft 2020-12) | Pinned input schemas and policy argument constraints |
| Console | Next.js 15 App Router, React 19, TypeScript strict | Server route handlers act as a backend-for-frontend |
| UI | Tailwind CSS 4, shadcn/ui (Radix), TanStack Query, next-themes | Accessible primitives, cached queries, light and dark themes |
| Quality | pytest + pytest-asyncio, ruff, mypy `--strict`, ESLint, Playwright | 125 backend tests and an end-to-end console smoke test |
| Packaging | Docker Compose, Makefile, native local services | Runs with Docker or with local Postgres and Redis binaries |

## Key engineering decisions

**Agents see the pin, not the upstream.** `tools/list` builds every entry from `approved_definition`. Even in
the gap between an upstream change and the next sync, no unreviewed text reaches the model.

**Canonical JSON without Unicode normalization.** The hash covers sorted-key JSON with `ensure_ascii=True`, so
invisible code points become visible `\uXXXX` escapes. Normalizing first would let look-alike edits keep the
same hash.

**Approval is compare-and-set.** `approve` needs the `expected_hash` the reviewer actually saw. If the upstream
changes while the diff is open, the approval fails instead of pinning text nobody reviewed. Rejecting a tool
drops its live pin, so flipping back to an old definition cannot bring it back.

**Fail closed everywhere.** Pinned schemas are compiled once per hash (LRU-cached). A schema or regex the
gateway cannot evaluate denies the call instead of letting arguments through. With no matching allow rule, the
answer is deny.

**Output is flagged, not blocked.** Tool results are scanned for invisible characters and steering phrases.
Findings go into `_meta["dev.toolgate/output-findings"]` and the audit reason. Blocking would break legitimate
tools that quote untrusted text, so the agent host decides. *Trade-off:* this is a signal, not a guarantee.

**Rate limits live in Redis Lua.** The token bucket refills and consumes in one script, so limits hold across
replicas without races. *Trade-off:* every rate-limited call costs one Redis round trip.

**The console holds no API key.** It is a public OAuth client of Toolgate itself (`toolgate-console`, scope
`toolgate:admin`, audience `<issuer>/api`). Tokens live in an AES-GCM sealed, httpOnly, SameSite=Lax cookie. The
relay checks Host (against DNS rebinding), Origin and Fetch Metadata, and dedupes refresh-token rotation. Every
action is attributed to the person who took it. The admin API key exists only for scripts and CI.

**The audit log is append-only twice over.** Triggers refuse `UPDATE`, `DELETE` and `TRUNCATE`. Separately, when
`TOOLGATE_DB_APP_ROLE` is set, migration `0002` grants that role only `SELECT` and `INSERT` on the table, because
a table owner could drop the triggers. Arguments are redacted before storage: secret-looking keys, bearer
tokens, card numbers (Luhn-checked), and secret values echoed in error messages.

**A health check only fails on silence.** The pool pings each upstream on an interval. Any JSON-RPC reply, even
"Method not found", counts as alive. Only timeouts and closed transports trigger a reconnect, so a server that
does not implement `ping` is not restarted over and over.

**Principal globs match every identity on a token.** A token carries both `user:<name>` and `client:<id>`, so a
`client:*` grant gives the tool to any user of any registered client. The seed data says this in a comment, and
the policy editor says it in its help text.

**Production refuses default secrets.** With `TOOLGATE_ENV=prod`, startup fails unless the admin key and session
secret are unique random values of 32 or more characters.

## Project structure

```text
toolgate-mcp-gateway/
├── backend/
│   ├── src/toolgate/
│   │   ├── auth/          OAuth 2.1 AS: DCR, PKCE, tokens, JWKS, login and consent pages, bearer middleware
│   │   ├── registry/      upstreams, tool snapshots, pins, change log, naming, diff
│   │   ├── federation/    supervised session pool, sync, /mcp server, GatewayService call pipeline
│   │   ├── scanner/       rules, Unicode decoding, classifier protocol, output checks -> ScanReport
│   │   ├── policy/        Pydantic policy models, evaluator, Redis token bucket, simulator
│   │   ├── audit/         append-only table, redaction, SSE broadcaster, OpenTelemetry
│   │   ├── admin/         health, readiness, overview, clients, principals
│   │   ├── common/        ToolDefinition canonicalization, Principal, pagination
│   │   ├── app.py         FastAPI factory and lifespan
│   │   ├── container.py   dependency wiring
│   │   ├── config.py      pydantic-settings (TOOLGATE_*)
│   │   └── seed.py        demo and red-team upstreams, policies, accounts
│   ├── fixtures/servers/  benign (weather, github, files, mailer, crm) and malicious MCP servers
│   ├── fixtures/demo.py   demo state (approvals, staged rug pull) and scripted agent traffic
│   ├── migrations/        Alembic 0001 schema + triggers, 0002 least-privilege app role
│   └── tests/             unit/, integration/, redteam/
├── web/
│   ├── src/app/           pages (overview, servers, tools, approvals, policies, activity) + api/ route handlers
│   ├── src/features/      definition diff, findings, policy editor and simulator, tool dialog, charts
│   ├── src/lib/server/    sealed session, BFF config, problem responses
│   └── e2e/               Playwright console smoke test
├── docs/                  screenshots, attack-blocked.json
├── scripts/               local-services.sh (native Postgres + Redis)
├── docker-compose.yml
└── Makefile
```

## Quickstart

### Local (no Docker)

Prerequisites: Python 3.12+, Node 22+ with pnpm 9, and local `postgres`, `redis-server` and `psql` binaries.

```bash
cp .env.example .env                  # backend settings
cp web/.env.example web/.env.local    # then set TOOLGATE_CONSOLE_SESSION_SECRET (32+ random chars)
#   python3 -c "import secrets; print(secrets.token_urlsafe(36))"

make setup          # python3.13 venv + backend deps, pnpm install
make services       # Postgres on :5501 and Redis on :6401, data in ./.data
make migrate seed   # schema, then demo + red-team upstreams, policies and accounts
make dev-api        # gateway + MCP endpoint on http://localhost:8101 (MCP at /mcp)
make dev-web        # console on http://localhost:3101
make demo traffic   # optional: approve the benign tools, stage the rug pull and send sample agent calls
```

Open <http://localhost:3101>. You are sent to Toolgate's own OAuth sign-in. Log in as **`alice` /
`toolgate-demo`** and click **Allow**.

`make seed` is additive: it only adds what is missing. `make seed-reset` deletes every upstream and policy
first. Seeding also prints a `client_credentials` client for machine agents. Stop the local services with
`make services-stop`.

### Docker Compose

```bash
cp .env.example .env
# set TOOLGATE_ADMIN_API_KEY, TOOLGATE_SESSION_SECRET and TOOLGATE_CONSOLE_SESSION_SECRET in .env
docker compose up --build
docker compose exec api toolgate seed
```

Compose runs Postgres 17, Redis 7, a one-shot `migrate` job, the API on `:8101` and the console on `:3101`.

### Connect an agent

Point any MCP client that supports OAuth at `http://localhost:8101/mcp`. It finds the authorization server
through `/.well-known/oauth-protected-resource/mcp`, registers itself through `/oauth/register`, and completes
code + PKCE in the browser. A machine agent can use the seeded `client_credentials` client instead:

```bash
curl -s http://localhost:8101/oauth/token \
  -d grant_type=client_credentials -d client_id="$CLIENT_ID" -d client_secret="$CLIENT_SECRET" \
  -d scope="mcp:tools.list mcp:tools.call"
```

New tools stay pending until an admin approves them in the console. The seeded `baseline-allow` policy then
lets every principal call the weather, translator, read-only GitHub, CRM lookup and file tools.

## Configuration

Backend settings use the `TOOLGATE_` prefix and are read from `.env` (see [`config.py`](backend/src/toolgate/config.py)).

| Variable | Default | Purpose |
| --- | --- | --- |
| `TOOLGATE_ENV` | `dev` | `dev`, `test` or `prod`. `prod` enforces strong secrets |
| `TOOLGATE_PUBLIC_URL` | `http://localhost:8101` | OAuth issuer; the MCP resource is `<url>/mcp`, the admin API is `<url>/api` |
| `TOOLGATE_DATABASE_URL` | `postgresql+asyncpg://toolgate@127.0.0.1:5501/toolgate` | Postgres DSN |
| `TOOLGATE_REDIS_URL` | `redis://127.0.0.1:6401/0` | Rate limits and audit fan-out |
| `TOOLGATE_ADMIN_API_KEY` | dev value | `X-Toolgate-Admin-Key` for scripts and CI |
| `TOOLGATE_SESSION_SECRET` | dev value | Signs login sessions and CSRF tokens |
| `TOOLGATE_CONSOLE_ORIGIN` | `http://localhost:3101` | Registers `<origin>/api/auth/callback` for the console client; empty disables it |
| `TOOLGATE_ACCESS_TOKEN_TTL_SECONDS` | `600` | Access token lifetime (60 to 3600) |
| `TOOLGATE_REFRESH_TOKEN_TTL_SECONDS` | `1209600` | Refresh token lifetime |
| `TOOLGATE_REGISTRATION_INITIAL_TOKEN` | unset | When set, dynamic client registration needs this bearer token |
| `TOOLGATE_CLASSIFIER` | `offline` | `offline` (deterministic), `anthropic` or `none` |
| `TOOLGATE_ANTHROPIC_API_KEY` / `_MODEL` | unset / `claude-opus-5-5` | Used when the classifier is `anthropic` |
| `TOOLGATE_AUTO_APPROVE_CLEAN_TOOLS` | `false` | Auto-approve new tools with zero findings |
| `TOOLGATE_REFRESH_INTERVAL_SECONDS` | `30` | Periodic `tools/list` re-sync |
| `TOOLGATE_UPSTREAM_CALL_TIMEOUT_SECONDS` | `30` | Per-call upstream timeout |
| `TOOLGATE_UPSTREAM_HEALTH_INTERVAL_SECONDS` | `15` | Upstream ping interval |
| `TOOLGATE_MCP_ALLOWED_HOSTS` / `_ORIGINS` | localhost patterns | DNS-rebinding protection on `/mcp` (comma-separated) |
| `TOOLGATE_CORS_ORIGINS` | `http://localhost:3101` | CORS allow-list |
| `TOOLGATE_OTEL_EXPORTER` | `none` | `none`, `console` or `otlp` |
| `TOOLGATE_OTEL_ENDPOINT` | unset | OTLP/HTTP traces endpoint |
| `TOOLGATE_DB_APP_ROLE` | unset | Least-privilege runtime role (no `UPDATE`/`DELETE` on audit) |
| `TOOLGATE_DEMO_FIXTURES` | `false` | Serve the HTTP CRM fixture at `/fixtures/crm/mcp` |
| `TOOLGATE_LOG_LEVEL` / `_LOG_JSON` | `INFO` / `false` | structlog output |

Console settings (`web/.env.local`, server-side only):

| Variable | Purpose |
| --- | --- |
| `TOOLGATE_API_ORIGIN` | Where the console's server reaches the API (can be an internal address) |
| `TOOLGATE_PUBLIC_URL` | The gateway's public URL, where browsers are sent to sign in |
| `TOOLGATE_CONSOLE_URL` | The console's own public URL; must match `TOOLGATE_CONSOLE_ORIGIN` |
| `TOOLGATE_CONSOLE_SESSION_SECRET` | 32+ characters; encrypts the session cookie. The console refuses to start without it |

## API overview

Interactive docs are served at `http://localhost:8101/docs`.

| Area | Endpoints |
| --- | --- |
| **MCP** | `GET` `POST` `DELETE /mcp`: Streamable HTTP. Needs a Bearer JWT with audience `<issuer>/mcp` and scope `mcp:tools.list` or `mcp:tools.call` |
| **Discovery** | `GET /.well-known/oauth-authorization-server`, `GET /.well-known/oauth-protected-resource[/mcp\|/api]`, `GET /oauth/jwks` |
| **OAuth** | `POST /oauth/register`, `GET` `POST /oauth/authorize`, `POST /oauth/login`, `POST /oauth/token`, `POST /oauth/revoke`, `GET /oauth/logout` |
| **Upstreams** | `GET` `POST /api/v1/upstreams`, `GET` `PATCH` `DELETE /api/v1/upstreams/{id}`, `POST /api/v1/upstreams/{id}/sync` |
| **Tools** | `GET /api/v1/tools`, `GET /api/v1/tools/{id}`, `GET /api/v1/tools/{id}/diff`, `POST /api/v1/tools/{id}/approve` `/reject` `/rescan`, `GET /api/v1/approvals` |
| **Policies** | `GET` `POST /api/v1/policies`, `GET` `PUT` `DELETE /api/v1/policies/{id}`, `POST /api/v1/policies/simulate` |
| **Audit** | `GET /api/v1/audit` (cursor pages), `GET /api/v1/audit/stats?hours=24`, `GET /api/v1/audit/stream` (SSE) |
| **Admin** | `GET /api/v1/overview`, `GET /api/v1/clients`, `GET /api/v1/principals`, `GET /healthz`, `GET /readyz` |

`/api/v1` needs a `toolgate:admin` JWT with audience `<issuer>/api`, or the `X-Toolgate-Admin-Key` header.

<details>
<summary>Example policy</summary>

```json
{
  "name": "writes-restricted",
  "rules": [
    {
      "id": "allow-issue-create",
      "effect": "allow",
      "principals": ["user:alice", "user:ops"],
      "tools": ["github__create_issue"],
      "arguments": {
        "type": "object",
        "properties": { "repo": { "enum": ["acme/payments", "acme/web"] } },
        "required": ["repo"]
      },
      "rate_limit": { "capacity": 5, "refill_per_minute": 10 }
    },
    { "id": "deny-branch-delete", "effect": "deny", "tools": ["github__delete_branch"] }
  ]
}
```

</details>

## Testing

```bash
make check          # ruff lint + format check, mypy --strict, pytest, eslint, tsc
make migrate-check  # alembic upgrade head && alembic check (fails on model/migration drift)
make build          # production console build
make e2e            # Playwright: OAuth sign-in, every page, a write, sign-out, Host/Origin refusals
make attack-report  # red-team suite -> docs/attack-blocked.json
```

| Suite | What it covers |
| --- | --- |
| `tests/unit` | Scanner rules and scoring, Unicode decoding, canonical hashing, PKCE, password and token hashing, policy evaluation, redaction, naming and diff |
| `tests/integration` | OAuth flows (code replay, refresh rotation and reuse, revocation, scope and audience challenges, login CSRF), admin API auth, approval and pin edge cases, federation and `list_changed`, Streamable HTTP upstreams, reconnect after an upstream crash, SSE delivery and replay, fail-closed schemas, migrations and grants |
| `tests/redteam` | Each malicious fixture runs through the real gateway, and the test asserts the attack is blocked |
| `web/e2e` | The console signs in through the real OAuth flow and every page renders; forged Origin and rebound Host headers are refused |

CI (`.github/workflows/ci.yml`) runs the backend on Python 3.12 and 3.13 against Postgres 17 and Redis 7,
including `alembic upgrade`, `check` and `downgrade`. It also lints, type-checks and builds the console.

## Roadmap

- [ ] Signed upstream manifests: verify a publisher signature before the first scan
- [ ] Per-tool output policies (redact or block, not only flag)
- [ ] Policy versions with diff and rollback in the console
- [ ] Multi-admin approval (two-person rule) for high-risk tools
- [ ] Resources and prompts federation, beyond tools
- [ ] Export the audit log to a SIEM (OTLP logs, webhook sink)
- [ ] Helm chart with a separate migration job and the least-privilege app role enabled by default

## License

[MIT](LICENSE)
