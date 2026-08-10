from __future__ import annotations

import hmac
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

import anyio
from sqlalchemy import select, update

from toolgate.auth import scopes as scope_utils
from toolgate.auth.models import AuthorizationCode, OAuthClient, RefreshToken, User
from toolgate.auth.passwords import hash_password, hash_token, new_token, verify_password
from toolgate.auth.pkce import is_valid_challenge, verify_s256
from toolgate.auth.schemas import (
    AuthorizationRequest,
    ClientOut,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    TokenResponse,
)
from toolgate.auth.tokens import InvalidTokenError, TokenService
from toolgate.config import CONSOLE_CLIENT_ID, Settings
from toolgate.db import SessionFactory, transaction, utcnow
from toolgate.logging import get_logger

log = get_logger(__name__)


class OAuthError(Exception):
    """An RFC 6749 section 5.2 error returned as JSON from the token, registration and revocation endpoints."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


class AuthorizeFatalError(Exception):
    """The client or redirect URI cannot be trusted, so the error is shown to the user instead of redirected."""


class AuthorizeRedirectError(Exception):
    def __init__(self, redirect_uri: str, error: str, description: str, state: str | None) -> None:
        super().__init__(description)
        self.redirect_uri = redirect_uri
        self.error = error
        self.description = description
        self.state = state


@dataclass(frozen=True, slots=True)
class ValidatedAuthorization:
    client_id: str
    client_name: str
    redirect_uri: str
    scopes: list[str]
    resource: str
    code_challenge: str
    state: str | None


@dataclass(frozen=True, slots=True)
class ClientCredentials:
    client_id: str
    client_secret: str | None
    method: str


class OAuthService:
    def __init__(self, sessions: SessionFactory, tokens: TokenService, settings: Settings) -> None:
        self._sessions = sessions
        self._tokens = tokens
        self._settings = settings

    @property
    def resources(self) -> dict[str, tuple[str, ...]]:
        return {
            self._settings.mcp_resource: scope_utils.MCP_SCOPES,
            self._settings.admin_resource: (scope_utils.ADMIN,),
        }

    async def register_client(
        self, request: ClientRegistrationRequest, *, initial_access_token: str | None
    ) -> ClientRegistrationResponse:
        expected = self._settings.registration_initial_token
        if expected is not None and not (
            initial_access_token and hmac.compare_digest(initial_access_token, expected.get_secret_value())
        ):
            raise OAuthError("invalid_token", "Registration requires a valid initial access token", 401)
        requested = scope_utils.parse(request.scope) or list(scope_utils.MCP_SCOPES)
        unknown = [s for s in requested if s not in scope_utils.ALL_SCOPES]
        if unknown:
            raise OAuthError("invalid_client_metadata", f"Unknown scope(s): {' '.join(unknown)}")

        client_id = f"tg_{uuid.uuid4().hex}"
        secret = new_token() if request.token_endpoint_auth_method != "none" else None
        issued_at = int(time.time())
        async with transaction(self._sessions) as session:
            session.add(
                OAuthClient(
                    client_id=client_id,
                    client_secret_hash=hash_token(secret) if secret else None,
                    client_name=request.client_name,
                    redirect_uris=request.redirect_uris,
                    grant_types=list(request.grant_types),
                    token_endpoint_auth_method=request.token_endpoint_auth_method,
                    scope=scope_utils.render(requested),
                    metadata_={
                        k: v
                        for k, v in {
                            "client_uri": request.client_uri,
                            "logo_uri": request.logo_uri,
                            "software_id": request.software_id,
                            "software_version": request.software_version,
                        }.items()
                        if v
                    },
                )
            )
        log.info("client_registered", client_id=client_id, name=request.client_name)
        return ClientRegistrationResponse(
            client_id=client_id,
            client_secret=secret,
            client_id_issued_at=issued_at,
            client_secret_expires_at=0 if secret else None,
            client_name=request.client_name,
            redirect_uris=request.redirect_uris,
            grant_types=list(request.grant_types),
            response_types=list(request.response_types),
            token_endpoint_auth_method=request.token_endpoint_auth_method,
            scope=scope_utils.render(requested),
        )

    async def get_client(self, client_id: str) -> OAuthClient | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(OAuthClient).where(OAuthClient.client_id == client_id, OAuthClient.is_active.is_(True))
            )

    async def list_clients(self) -> list[ClientOut]:
        async with self._sessions() as session:
            rows = await session.scalars(select(OAuthClient).order_by(OAuthClient.created_at.desc()))
            return [ClientOut.model_validate(r) for r in rows]

    def _resolve_scopes(self, requested: str | None, resource: str, client: OAuthClient) -> list[str]:
        allowed_for_resource = self.resources[resource]
        scopes = scope_utils.parse(requested) or list(allowed_for_resource)
        registered = set(scope_utils.parse(client.scope))
        bad = [s for s in scopes if s not in allowed_for_resource or (registered and s not in registered)]
        if bad:
            raise ValueError(f"scope not permitted for this client or resource: {' '.join(bad)}")
        return scopes

    async def validate_authorization(self, request: AuthorizationRequest) -> ValidatedAuthorization:
        client = await self.get_client(request.client_id)
        if client is None:
            raise AuthorizeFatalError("This application is not registered with Toolgate.")
        if request.redirect_uri is None:
            if len(client.redirect_uris) != 1:
                raise AuthorizeFatalError("The application did not say where to return you.")
            redirect_uri = client.redirect_uris[0]
        elif request.redirect_uri in client.redirect_uris:
            redirect_uri = request.redirect_uri
        else:
            raise AuthorizeFatalError("The return address does not match what the application registered.")

        def fail(error: str, description: str) -> AuthorizeRedirectError:
            return AuthorizeRedirectError(redirect_uri, error, description, request.state)

        if request.response_type != "code":
            raise fail("unsupported_response_type", "Only the authorization code flow is supported")
        if "authorization_code" not in client.grant_types:
            raise fail("unauthorized_client", "Client is not registered for the authorization code grant")
        if not request.code_challenge:
            raise fail("invalid_request", "PKCE is required: send code_challenge with code_challenge_method=S256")
        if request.code_challenge_method != "S256":
            raise fail("invalid_request", "Only the S256 code_challenge_method is accepted")
        if not is_valid_challenge(request.code_challenge):
            raise fail("invalid_request", "code_challenge must be a 43 character base64url SHA-256 digest")
        resource = (request.resource or self._settings.mcp_resource).rstrip("/")
        if resource not in self.resources:
            raise fail("invalid_target", "Unknown resource indicator")
        try:
            scopes = self._resolve_scopes(request.scope, resource, client)
        except ValueError as exc:
            raise fail("invalid_scope", str(exc)) from exc
        return ValidatedAuthorization(
            client_id=client.client_id,
            client_name=client.client_name,
            redirect_uri=redirect_uri,
            scopes=scopes,
            resource=resource,
            code_challenge=request.code_challenge,
            state=request.state,
        )

    async def issue_code(self, auth: ValidatedAuthorization, user: User) -> str:
        if scope_utils.ADMIN in auth.scopes and not user.is_admin:
            raise AuthorizeRedirectError(
                auth.redirect_uri, "access_denied", "Admin scope requires an administrator account", auth.state
            )
        code = new_token()
        async with transaction(self._sessions) as session:
            session.add(
                AuthorizationCode(
                    code_hash=hash_token(code),
                    client_id=auth.client_id,
                    user_id=user.id,
                    redirect_uri=auth.redirect_uri,
                    scope=scope_utils.render(auth.scopes),
                    resource=auth.resource,
                    code_challenge=auth.code_challenge,
                    expires_at=utcnow() + timedelta(seconds=self._settings.auth_code_ttl_seconds),
                )
            )
        return code

    async def authenticate_client(self, creds: ClientCredentials) -> OAuthClient:
        client = await self.get_client(creds.client_id)
        if client is None:
            raise OAuthError("invalid_client", "Unknown client", 401)
        if client.token_endpoint_auth_method == "none":
            if creds.client_secret:
                raise OAuthError("invalid_client", "Public clients must not send a secret", 401)
            return client
        if creds.method != client.token_endpoint_auth_method:
            raise OAuthError(
                "invalid_client", f"Client must authenticate with {client.token_endpoint_auth_method}", 401
            )
        if not creds.client_secret or not client.client_secret_hash:
            raise OAuthError("invalid_client", "Client authentication failed", 401)
        if not hmac.compare_digest(hash_token(creds.client_secret), client.client_secret_hash):
            raise OAuthError("invalid_client", "Client authentication failed", 401)
        return client

    def _issue(
        self, *, subject: str, client: OAuthClient, scopes: list[str], resource: str, refresh: str | None
    ) -> tuple[TokenResponse, str]:
        issued = self._tokens.issue(subject=subject, client_id=client.client_id, scopes=scopes, resource=resource)
        response = TokenResponse(
            access_token=issued.token,
            expires_in=issued.expires_in,
            scope=scope_utils.render(scopes),
            refresh_token=refresh,
        )
        return response, issued.jti

    async def exchange_code(
        self, client: OAuthClient, *, code: str, redirect_uri: str | None, verifier: str, resource: str | None
    ) -> TokenResponse:
        now = utcnow()
        replayed_family: uuid.UUID | None = None
        replayed_jti: str | None = None
        response: TokenResponse | None = None
        async with transaction(self._sessions) as session:
            record = await session.scalar(
                select(AuthorizationCode).where(AuthorizationCode.code_hash == hash_token(code)).with_for_update()
            )
            if record is None or record.client_id != client.client_id:
                raise OAuthError("invalid_grant", "Authorization code is invalid")
            if record.consumed_at is not None:
                replayed_family = record.token_family
                replayed_jti = record.access_token_jti
            else:
                if record.expires_at < now:
                    raise OAuthError("invalid_grant", "Authorization code expired")
                if redirect_uri != record.redirect_uri:
                    raise OAuthError("invalid_grant", "redirect_uri does not match the authorization request")
                if not verify_s256(verifier, record.code_challenge):
                    raise OAuthError("invalid_grant", "PKCE verification failed")
                if resource is not None and resource.rstrip("/") != record.resource:
                    raise OAuthError("invalid_target", "resource does not match the authorization request")
                record.consumed_at = now
                user = await session.get(User, record.user_id)
                if user is None:
                    raise OAuthError("invalid_grant", "The authorizing user no longer exists")
                scopes = scope_utils.parse(record.scope)
                refresh = new_token() if "refresh_token" in client.grant_types else None
                response, jti = self._issue(
                    subject=user.subject, client=client, scopes=scopes, resource=record.resource, refresh=refresh
                )
                record.access_token_jti = jti
                if refresh is not None:
                    session.add(
                        RefreshToken(
                            token_hash=hash_token(refresh),
                            family_id=record.token_family,
                            client_id=client.client_id,
                            subject=user.subject,
                            scope=record.scope,
                            resource=record.resource,
                            access_token_jti=jti,
                            expires_at=now + timedelta(seconds=self._settings.refresh_token_ttl_seconds),
                        )
                    )
        if replayed_family is not None:
            # RFC 6749 section 4.1.2: a reused code means it leaked; revoke everything it produced,
            # including access tokens that are still within their lifetime.
            await self._revoke_family(replayed_family, extra_jtis=[replayed_jti] if replayed_jti else [])
            log.warning("authorization_code_replay", client_id=client.client_id)
            raise OAuthError("invalid_grant", "Authorization code was already used")
        assert response is not None
        return response

    async def refresh(self, client: OAuthClient, *, refresh_token: str, scope: str | None) -> TokenResponse:
        now = utcnow()
        reused_family: uuid.UUID | None = None
        response: TokenResponse | None = None
        async with transaction(self._sessions) as session:
            record = await session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)).with_for_update()
            )
            if record is None or record.client_id != client.client_id:
                raise OAuthError("invalid_grant", "Refresh token is invalid")
            if record.revoked_at is not None or record.rotated_at is not None:
                reused_family = record.family_id
            else:
                if record.expires_at < now:
                    raise OAuthError("invalid_grant", "Refresh token expired")
                granted = scope_utils.parse(record.scope)
                requested = scope_utils.parse(scope) or granted
                if not set(requested) <= set(granted):
                    raise OAuthError("invalid_scope", "Cannot widen scope on refresh")
                record.rotated_at = now
                rotated = new_token()
                response, jti = self._issue(
                    subject=record.subject, client=client, scopes=requested, resource=record.resource, refresh=rotated
                )
                session.add(
                    RefreshToken(
                        token_hash=hash_token(rotated),
                        family_id=record.family_id,
                        client_id=client.client_id,
                        subject=record.subject,
                        scope=record.scope,
                        resource=record.resource,
                        access_token_jti=jti,
                        expires_at=record.expires_at,
                    )
                )
        if reused_family is not None:
            # Rotation reuse detection (OAuth 2.1 section 4.3.1): a rotated token showing up again means
            # two parties hold the family, so the whole family dies.
            await self._revoke_family(reused_family)
            log.warning("refresh_token_reuse", client_id=client.client_id)
            raise OAuthError("invalid_grant", "Refresh token was already used")
        assert response is not None
        return response

    async def client_credentials(
        self, client: OAuthClient, *, scope: str | None, resource: str | None
    ) -> TokenResponse:
        if "client_credentials" not in client.grant_types or client.token_endpoint_auth_method == "none":
            raise OAuthError("unauthorized_client", "Client is not allowed to use client_credentials")
        target = (resource or self._settings.mcp_resource).rstrip("/")
        if target not in self.resources:
            raise OAuthError("invalid_target", "Unknown resource indicator")
        try:
            scopes = self._resolve_scopes(scope, target, client)
        except ValueError as exc:
            raise OAuthError("invalid_scope", str(exc)) from exc
        if scope_utils.ADMIN in scopes:
            raise OAuthError("invalid_scope", "Machine clients cannot hold the admin scope")
        response, _ = self._issue(
            subject=f"client:{client.client_id}", client=client, scopes=scopes, resource=target, refresh=None
        )
        return response

    async def revoke(self, client: OAuthClient, token: str) -> None:
        async with self._sessions() as session:
            record = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)))
        if record is not None:
            if record.client_id == client.client_id:
                await self._revoke_family(record.family_id)
            return
        for audience in self.resources:
            try:
                claims = self._tokens.decode(token, audience=audience)
            except InvalidTokenError:
                continue
            if claims.client_id == client.client_id:
                await self._tokens.revoke(claims)
            return

    async def _revoke_family(self, family_id: uuid.UUID, *, extra_jtis: list[str] | None = None) -> None:
        async with transaction(self._sessions) as session:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            jtis = await session.scalars(
                select(RefreshToken.access_token_jti).where(
                    RefreshToken.family_id == family_id, RefreshToken.access_token_jti.is_not(None)
                )
            )
            pending = [*(extra_jtis or []), *(j for j in jtis if j)]
        await self._tokens.revoke_ids(sorted(set(pending)))

    async def authenticate_user(self, username: str, password: str) -> User | None:
        async with self._sessions() as session:
            user = await session.scalar(select(User).where(User.username == username))
        # scrypt is deliberately slow and memory hungry; keep it off the event loop.
        if user is None:
            # Burn comparable time so response latency does not reveal which usernames exist.
            await anyio.to_thread.run_sync(verify_password, password, _DUMMY_HASH)
            return None
        valid = await anyio.to_thread.run_sync(verify_password, password, user.password_hash)
        return user if valid else None

    async def ensure_console_client(self) -> None:
        """The admin console is a public OAuth client that only ever asks for the admin scope."""
        redirect_uri = self._settings.console_redirect_uri
        if redirect_uri is None:
            return
        async with transaction(self._sessions) as session:
            client = await session.scalar(select(OAuthClient).where(OAuthClient.client_id == CONSOLE_CLIENT_ID))
            if client is None:
                client = OAuthClient(client_id=CONSOLE_CLIENT_ID, client_secret_hash=None, metadata_={})
                session.add(client)
            client.client_name = "Toolgate Console"
            client.redirect_uris = [redirect_uri]
            client.grant_types = ["authorization_code", "refresh_token"]
            client.token_endpoint_auth_method = "none"
            client.scope = scope_utils.ADMIN
            client.is_active = True

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        async with self._sessions() as session:
            return await session.get(User, user_id)

    async def ensure_user(self, username: str, password: str, *, display_name: str, is_admin: bool) -> User:
        async with transaction(self._sessions) as session:
            user = await session.scalar(select(User).where(User.username == username))
            if user is None:
                user = User(username=username, display_name=display_name, is_admin=is_admin, password_hash="")
                session.add(user)
            user.password_hash = hash_password(password)
            user.display_name = display_name
            user.is_admin = is_admin
            await session.flush()
            return user

    async def list_users(self) -> list[User]:
        async with self._sessions() as session:
            return list((await session.scalars(select(User).order_by(User.username))).all())


_DUMMY_HASH = hash_password("timing-equalizer")
