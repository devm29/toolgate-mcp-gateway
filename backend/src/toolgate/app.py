from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from toolgate import __version__
from toolgate.admin.routes import router as admin_router
from toolgate.audit.routes import router as audit_router
from toolgate.audit.telemetry import install_global
from toolgate.auth.routes import router as auth_router
from toolgate.config import Environment, Settings, get_settings
from toolgate.container import Container, build_container
from toolgate.errors import install_error_handlers
from toolgate.federation.mcp_server import McpEndpoint
from toolgate.logging import configure_logging, get_logger
from toolgate.policy.routes import router as policy_router
from toolgate.registry.routes import router as registry_router

log = get_logger(__name__)

DEMO_HTTP_FIXTURES = ("crm",)


def create_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
    start_federation: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            active = container or await build_container(settings)
            if container is None:
                stack.push_async_callback(active.close)
                install_global(active.tracer_provider)
            endpoint = McpEndpoint(active.gateway, active.tokens, settings)
            app.state.container = active
            app.state.mcp_endpoint = endpoint
            await stack.enter_async_context(endpoint.session_manager.run())
            for fixture_app in app.state.demo_fixture_managers:
                await stack.enter_async_context(fixture_app.run())
            if start_federation:
                await active.start_federation(refresh=settings.env is not Environment.TEST)
            log.info("toolgate_started", version=__version__, issuer=settings.issuer, mcp=settings.mcp_resource)
            yield
            log.info("toolgate_stopping")

    app = FastAPI(
        title="Toolgate",
        version=__version__,
        summary="Zero-trust MCP gateway and tool registry",
        lifespan=lifespan,
    )
    app.state.demo_fixture_managers = []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id", "Mcp-Protocol-Version", "Last-Event-ID"],
        expose_headers=["Mcp-Session-Id", "WWW-Authenticate"],
    )
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(registry_router)
    app.include_router(policy_router)
    app.include_router(audit_router)

    class _McpProxy:
        """Resolves the endpoint at request time because it is built inside the lifespan."""

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            endpoint: McpEndpoint = app.state.mcp_endpoint
            await endpoint.asgi(scope, receive, send)

    app.router.routes.append(Route("/mcp", endpoint=_McpProxy(), methods=["GET", "POST", "DELETE"]))

    if settings.demo_fixtures:
        from fixtures.servers import crm

        for name in DEMO_HTTP_FIXTURES:
            fixture = {"crm": crm.server}[name]()
            sub_app = fixture.http_app(path="/mcp")
            app.state.demo_fixture_managers.append(fixture.build().session_manager)
            app.router.routes.append(Mount(f"/fixtures/{name}", app=sub_app))
    return app
