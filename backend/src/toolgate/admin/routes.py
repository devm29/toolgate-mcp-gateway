from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from toolgate import __version__
from toolgate.audit.schemas import AuditStats
from toolgate.auth.dependencies import AdminPrincipal
from toolgate.auth.schemas import ClientOut
from toolgate.container import Container, get_container
from toolgate.registry.models import ToolStatus, UpstreamStatus
from toolgate.scanner.models import RiskLevel

router = APIRouter(tags=["admin"])
ContainerDep = Annotated[Container, Depends(get_container)]


class Overview(BaseModel):
    upstreams: int
    upstreams_connected: int
    tools_total: int
    tools_exposed: int
    awaiting_review: int
    quarantined: int
    by_status: dict[ToolStatus, int]
    by_risk: dict[RiskLevel, int]
    traffic: AuditStats


class PrincipalOut(BaseModel):
    id: str
    label: str
    kind: str


class Health(BaseModel):
    status: str
    version: str


@router.get("/healthz", response_model=Health)
async def healthz() -> Health:
    return Health(status="ok", version=__version__)


@router.get("/readyz", response_model=Health)
async def readyz(container: ContainerDep) -> Health:
    async with container.sessions() as session:
        await session.execute(text("SELECT 1"))
    await container.redis.ping()
    return Health(status="ready", version=__version__)


@router.get("/api/v1/overview", response_model=Overview)
async def overview(container: ContainerDep, _: AdminPrincipal) -> Overview:
    upstreams = await container.registry.list_upstreams()
    by_status = {status: 0 for status in ToolStatus} | await container.registry.status_counts()
    by_risk = {level: 0 for level in RiskLevel} | await container.registry.risk_counts()
    exposed = len(await container.registry.servable_tools())
    return Overview(
        upstreams=len(upstreams),
        upstreams_connected=sum(1 for u in upstreams if u.status is UpstreamStatus.CONNECTED),
        tools_total=sum(by_status.values()),
        tools_exposed=exposed,
        awaiting_review=by_status[ToolStatus.PENDING] + by_status[ToolStatus.QUARANTINED],
        quarantined=by_status[ToolStatus.QUARANTINED],
        by_status=by_status,
        by_risk=by_risk,
        traffic=await container.audit.stats(hours=24),
    )


@router.get("/api/v1/clients", response_model=list[ClientOut])
async def clients(container: ContainerDep, _: AdminPrincipal) -> list[ClientOut]:
    return await container.oauth.list_clients()


@router.get("/api/v1/principals", response_model=list[PrincipalOut])
async def principals(container: ContainerDep, _: AdminPrincipal) -> list[PrincipalOut]:
    users = await container.oauth.list_users()
    oauth_clients = await container.oauth.list_clients()
    return [
        *(PrincipalOut(id=u.subject, label=u.display_name, kind="user") for u in users),
        *(PrincipalOut(id=f"client:{c.client_id}", label=c.client_name, kind="client") for c in oauth_clients),
    ]
