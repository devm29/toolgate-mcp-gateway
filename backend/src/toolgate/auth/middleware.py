from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

from toolgate.auth.tokens import InvalidTokenError, TokenService
from toolgate.common.principal import Principal

PRINCIPAL_STATE_KEY = "toolgate.principal"


class BearerAuthMiddleware:
    """Guards the MCP endpoint. Runs before the MCP transport so unauthenticated bytes never reach it.

    Failures follow RFC 6750 plus RFC 9728: the WWW-Authenticate header points clients at the protected
    resource metadata, which is how MCP clients discover the authorization server.
    """

    def __init__(
        self,
        app: ASGIApp,
        tokens: TokenService,
        *,
        audience: str,
        resource_metadata_url: str,
        required_scopes: tuple[str, ...] = (),
    ) -> None:
        self._app = app
        self._tokens = tokens
        self._audience = audience
        self._metadata_url = resource_metadata_url
        self._required = required_scopes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        header = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"authorization"), "")
        if not header.lower().startswith("bearer "):
            await self._challenge(send, 401, None, "Bearer token required")
            return
        try:
            principal = await self._tokens.verify(header[7:].strip(), audience=self._audience)
        except InvalidTokenError as exc:
            await self._challenge(send, 401, "invalid_token", str(exc))
            return
        if not any(principal.has_scope(s) for s in self._required):
            await self._challenge(send, 403, "insufficient_scope", "Token lacks MCP scopes")
            return
        scope.setdefault("state", {})[PRINCIPAL_STATE_KEY] = principal
        await self._app(scope, receive, send)

    async def _challenge(self, send: Send, status: int, error: str | None, description: str) -> None:
        parts = [f'resource_metadata="{self._metadata_url}"']
        if error:
            parts.append(f'error="{error}"')
            parts.append(f'error_description="{description}"')
        if status == 403:
            parts.append(f'scope="{" ".join(self._required)}"')
        body = json.dumps({"error": error or "unauthorized", "error_description": description}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", ("Bearer " + ", ".join(parts)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def principal_from_scope(scope: Scope) -> Principal | None:
    state = scope.get("state") or {}
    principal = state.get(PRINCIPAL_STATE_KEY)
    return principal if isinstance(principal, Principal) else None
