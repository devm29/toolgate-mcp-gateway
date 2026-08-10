from __future__ import annotations

import base64
import binascii
from typing import Annotated, Any
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError

from toolgate.auth import scopes as scope_utils
from toolgate.auth.models import User
from toolgate.auth.schemas import AuthorizationRequest, ClientRegistrationRequest, ClientRegistrationResponse
from toolgate.auth.service import (
    AuthorizeFatalError,
    AuthorizeRedirectError,
    ClientCredentials,
    OAuthError,
    ValidatedAuthorization,
)
from toolgate.auth.sessions import COOKIE_NAME, LOGIN_NONCE_COOKIE, LOGIN_NONCE_TTL_SECONDS
from toolgate.auth.templates import consent_page, error_page, login_page, signed_out_page
from toolgate.container import Container, get_container

router = APIRouter(tags=["oauth"])
ContainerDep = Annotated[Container, Depends(get_container)]

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
# Auth pages carry credentials and consent buttons, so they must never render inside another site's frame.
PAGE_HEADERS = {
    **NO_STORE,
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
    "Referrer-Policy": "no-referrer",
}
AUTHORIZE_PARAMS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "state",
    "scope",
    "resource",
)


def _oauth_error(exc: OAuthError, *, basic_auth: bool = False) -> JSONResponse:
    headers = dict(NO_STORE)
    if exc.status_code == 401 and basic_auth:
        headers["WWW-Authenticate"] = 'Basic realm="toolgate"'
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description}, status_code=exc.status_code, headers=headers
    )


def _redirect_with(uri: str, params: dict[str, str | None]) -> RedirectResponse:
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend((k, v) for k, v in params.items() if v is not None)
    return RedirectResponse(urlunsplit(parts._replace(query=urlencode(query))), status_code=303)


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata(container: ContainerDep) -> dict[str, Any]:
    issuer = container.settings.issuer
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "jwks_uri": f"{issuer}/oauth/jwks",
        "scopes_supported": list(scope_utils.ALL_SCOPES),
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": f"{issuer}/docs",
    }


def _resource_metadata(container: Container, resource: str, scopes: tuple[str, ...]) -> dict[str, Any]:
    return {
        "resource": resource,
        "authorization_servers": [container.settings.issuer],
        "scopes_supported": list(scopes),
        "bearer_methods_supported": ["header"],
        "resource_signing_alg_values_supported": ["RS256"],
        "resource_name": "Toolgate MCP gateway",
    }


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
async def mcp_resource_metadata(container: ContainerDep) -> dict[str, Any]:
    return _resource_metadata(container, container.settings.mcp_resource, scope_utils.MCP_SCOPES)


@router.get("/.well-known/oauth-protected-resource/api")
async def admin_resource_metadata(container: ContainerDep) -> dict[str, Any]:
    return _resource_metadata(container, container.settings.admin_resource, (scope_utils.ADMIN,))


@router.get("/oauth/jwks")
async def jwks(container: ContainerDep) -> dict[str, Any]:
    return container.keys.jwks()


@router.post(
    "/oauth/register", status_code=201, response_model=ClientRegistrationResponse, response_model_exclude_none=True
)
async def register_client(
    request: Request, container: ContainerDep, authorization: Annotated[str | None, Header()] = None
) -> Response:
    ip = request.client.host if request.client else "unknown"
    limit = await container.rate_limiter.consume(f"rl:register:{ip}", container.registration_limit)
    if not limit.allowed:
        return JSONResponse(
            {"error": "slow_down", "error_description": "Too many registrations"},
            status_code=429,
            headers={"Retry-After": str(int(limit.retry_after_seconds) + 1)},
        )
    try:
        payload = ClientRegistrationRequest.model_validate(await request.json())
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first.get("loc", ()))
        message = f"{field}: {first.get('msg')}" if field else str(first.get("msg"))
        return _oauth_error(OAuthError("invalid_client_metadata", message))
    except ValueError:
        return _oauth_error(OAuthError("invalid_client_metadata", "Body must be a JSON object"))
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    try:
        registered = await container.oauth.register_client(payload, initial_access_token=token)
    except OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(registered.model_dump(exclude_none=True), status_code=201, headers=NO_STORE)


async def _current_user(request: Request, container: Container) -> User | None:
    user_id = container.login_sessions.read(request.cookies.get(COOKIE_NAME))
    return await container.oauth.get_user(user_id) if user_id else None


def _page(html: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(html, status_code=status_code, headers=PAGE_HEADERS)


def _login_response(
    request: Request,
    container: Container,
    *,
    return_to: str,
    status_code: int = 200,
    error: str | None = None,
    username: str = "",
) -> HTMLResponse:
    nonce = request.cookies.get(LOGIN_NONCE_COOKIE) or container.login_sessions.new_login_nonce()
    csrf = container.login_sessions.login_csrf(nonce, return_to)
    response = _page(login_page(return_to=return_to, csrf=csrf, error=error, username=username), status_code)
    response.set_cookie(
        LOGIN_NONCE_COOKIE,
        nonce,
        max_age=LOGIN_NONCE_TTL_SECONDS,
        httponly=True,
        secure=container.login_sessions.secure,
        samesite="lax",
        path="/oauth",
    )
    return response


def _validated_or_response(exc: Exception, issuer: str) -> Response:
    if isinstance(exc, AuthorizeRedirectError):
        return _redirect_with(
            exc.redirect_uri,
            {"error": exc.error, "error_description": exc.description, "state": exc.state, "iss": issuer},
        )
    return _page(error_page(str(exc)), 400)


def _consent_fields(auth: ValidatedAuthorization, raw: dict[str, str]) -> dict[str, str]:
    return {k: raw[k] for k in AUTHORIZE_PARAMS if raw.get(k)}


def _csrf_parts(auth: ValidatedAuthorization) -> tuple[str, ...]:
    return (auth.client_id, auth.redirect_uri, auth.code_challenge, auth.resource, " ".join(auth.scopes))


@router.get("/oauth/authorize", response_class=HTMLResponse)
async def authorize(request: Request, container: ContainerDep) -> Response:
    raw = dict(request.query_params)
    try:
        auth_request = AuthorizationRequest.model_validate(raw)
    except ValidationError:
        return _page(error_page("The authorization request is missing required parameters."), 400)
    try:
        auth = await container.oauth.validate_authorization(auth_request)
    except (AuthorizeFatalError, AuthorizeRedirectError) as exc:
        return _validated_or_response(exc, container.settings.issuer)

    user = await _current_user(request, container)
    if user is None:
        return _login_response(request, container, return_to=f"/oauth/authorize?{request.url.query}")

    cookie = request.cookies[COOKIE_NAME]
    hidden = _consent_fields(auth, raw)
    hidden["csrf"] = container.login_sessions.csrf_token(cookie, *_csrf_parts(auth))
    page = consent_page(
        client_name=auth.client_name,
        redirect_uri=auth.redirect_uri,
        scopes=auth.scopes,
        username=user.display_name,
        hidden=hidden,
    )
    return _page(page)


@router.post("/oauth/authorize")
async def authorize_decision(request: Request, container: ContainerDep) -> Response:
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    try:
        auth = await container.oauth.validate_authorization(AuthorizationRequest.model_validate(form))
    except ValidationError:
        return _page(error_page("The authorization request is missing required parameters."), 400)
    except (AuthorizeFatalError, AuthorizeRedirectError) as exc:
        return _validated_or_response(exc, container.settings.issuer)

    cookie = request.cookies.get(COOKIE_NAME)
    user = await _current_user(request, container)
    if user is None or cookie is None:
        return _page(error_page("Your sign-in expired. Start again from the application."), 401)
    if not container.login_sessions.check_csrf(form.get("csrf", ""), cookie, *_csrf_parts(auth)):
        return _page(error_page("This consent form is no longer valid."), 403)

    issuer = container.settings.issuer
    if form.get("decision") != "allow":
        return _redirect_with(
            auth.redirect_uri,
            {"error": "access_denied", "error_description": "The user declined", "state": auth.state, "iss": issuer},
        )
    try:
        code = await container.oauth.issue_code(auth, user)
    except AuthorizeRedirectError as exc:
        return _validated_or_response(exc, issuer)
    return _redirect_with(auth.redirect_uri, {"code": code, "state": auth.state, "iss": issuer})


@router.post("/oauth/login", response_class=HTMLResponse)
async def login(
    request: Request,
    container: ContainerDep,
    username: Annotated[str, Form(max_length=64)],
    password: Annotated[str, Form(max_length=256)],
    return_to: Annotated[str, Form(max_length=4000)],
    csrf: Annotated[str, Form(max_length=128)] = "",
) -> Response:
    if not return_to.startswith("/oauth/authorize?"):
        return _page(error_page("Invalid return address."), 400)
    if not container.login_sessions.check_login_csrf(csrf, request.cookies.get(LOGIN_NONCE_COOKIE), return_to):
        return _login_response(
            request, container, return_to=return_to, status_code=403, error="This sign-in form expired. Try again."
        )
    ip = request.client.host if request.client else "unknown"
    limit = await container.rate_limiter.consume(f"rl:login:{ip}", container.login_limit)
    if not limit.allowed:
        return _login_response(
            request,
            container,
            return_to=return_to,
            status_code=429,
            error="Too many attempts. Wait a minute and try again.",
            username=username,
        )
    user = await container.oauth.authenticate_user(username, password)
    if user is None:
        return _login_response(
            request,
            container,
            return_to=return_to,
            status_code=401,
            error="That username and password don't match.",
            username=username,
        )
    response = RedirectResponse(return_to, status_code=303)
    response.delete_cookie(LOGIN_NONCE_COOKIE, path="/oauth")
    response.set_cookie(
        COOKIE_NAME,
        container.login_sessions.issue(user.id),
        max_age=container.login_sessions.ttl,
        httponly=True,
        secure=container.login_sessions.secure,
        samesite="lax",
        path="/oauth",
    )
    return response


@router.get("/oauth/logout")
async def logout(
    container: ContainerDep, client_id: str | None = None, post_logout_redirect_uri: str | None = None
) -> Response:
    """Ends the sign-in session. Redirects back only to an origin the named client registered."""
    target: str | None = None
    if client_id and post_logout_redirect_uri:
        client = await container.oauth.get_client(client_id)
        wanted = urlsplit(post_logout_redirect_uri)
        allowed = {(urlsplit(u).scheme, urlsplit(u).netloc) for u in (client.redirect_uris if client else [])}
        if (wanted.scheme, wanted.netloc) in allowed and not wanted.fragment:
            target = post_logout_redirect_uri
    response: Response = RedirectResponse(target, status_code=303) if target else _page(signed_out_page())
    response.delete_cookie(COOKIE_NAME, path="/oauth")
    response.headers["Cache-Control"] = "no-store"
    return response


def _client_credentials(form: dict[str, str], authorization: str | None) -> ClientCredentials:
    if authorization and authorization.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode()
            client_id, _, secret = decoded.partition(":")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise OAuthError("invalid_client", "Malformed Basic credentials", 401) from exc
        # RFC 6749 section 2.3.1: both parts are form-urlencoded before being joined, so '+' means space.
        return ClientCredentials(unquote_plus(client_id), unquote_plus(secret), "client_secret_basic")
    posted_id = form.get("client_id")
    if not posted_id:
        raise OAuthError("invalid_client", "Client authentication is required", 401)
    posted_secret = form.get("client_secret")
    return ClientCredentials(posted_id, posted_secret, "client_secret_post" if posted_secret else "none")


@router.post("/oauth/token")
async def token(
    request: Request, container: ContainerDep, authorization: Annotated[str | None, Header()] = None
) -> Response:
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    basic = bool(authorization and authorization.lower().startswith("basic "))
    try:
        client = await container.oauth.authenticate_client(_client_credentials(form, authorization))
        grant = form.get("grant_type")
        if grant == "authorization_code":
            if not form.get("code") or not form.get("code_verifier"):
                raise OAuthError("invalid_request", "code and code_verifier are required")
            result = await container.oauth.exchange_code(
                client,
                code=form["code"],
                redirect_uri=form.get("redirect_uri"),
                verifier=form["code_verifier"],
                resource=form.get("resource"),
            )
        elif grant == "refresh_token":
            if not form.get("refresh_token"):
                raise OAuthError("invalid_request", "refresh_token is required")
            result = await container.oauth.refresh(client, refresh_token=form["refresh_token"], scope=form.get("scope"))
        elif grant == "client_credentials":
            result = await container.oauth.client_credentials(
                client, scope=form.get("scope"), resource=form.get("resource")
            )
        else:
            raise OAuthError("unsupported_grant_type", f"Unsupported grant_type '{grant}'")
    except OAuthError as exc:
        return _oauth_error(exc, basic_auth=basic)
    return JSONResponse(result.model_dump(exclude_none=True), headers=NO_STORE)


@router.post("/oauth/revoke")
async def revoke(
    request: Request, container: ContainerDep, authorization: Annotated[str | None, Header()] = None
) -> Response:
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    basic = bool(authorization and authorization.lower().startswith("basic "))
    try:
        client = await container.oauth.authenticate_client(_client_credentials(form, authorization))
    except OAuthError as exc:
        return _oauth_error(exc, basic_auth=basic)
    if form.get("token"):
        await container.oauth.revoke(client, form["token"])
    return Response(status_code=200, headers=NO_STORE)
