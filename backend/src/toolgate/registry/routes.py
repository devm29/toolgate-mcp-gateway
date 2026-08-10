from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from toolgate.auth.dependencies import AdminPrincipal
from toolgate.common.pagination import Page, PageParams
from toolgate.container import Container, get_container
from toolgate.registry.diff import DefinitionDiff
from toolgate.registry.schemas import (
    ApprovalItem,
    ApproveRequest,
    RejectRequest,
    SyncResult,
    ToolDetail,
    ToolFilters,
    ToolSummary,
    UpstreamCreate,
    UpstreamOut,
    UpstreamUpdate,
)
from toolgate.scanner.models import ScanReport

router = APIRouter(prefix="/api/v1", tags=["registry"])
ContainerDep = Annotated[Container, Depends(get_container)]


@router.get("/upstreams", response_model=list[UpstreamOut])
async def list_upstreams(container: ContainerDep, _: AdminPrincipal) -> list[UpstreamOut]:
    return await container.registry.list_upstreams()


@router.post("/upstreams", response_model=UpstreamOut, status_code=status.HTTP_201_CREATED)
async def create_upstream(payload: UpstreamCreate, container: ContainerDep, _: AdminPrincipal) -> UpstreamOut:
    upstream = await container.registry.create_upstream(payload)
    if upstream.enabled:
        await container.pool.ensure(upstream)
    return await container.registry.get_upstream_out(upstream.id)


@router.get("/upstreams/{upstream_id}", response_model=UpstreamOut)
async def get_upstream(upstream_id: uuid.UUID, container: ContainerDep, _: AdminPrincipal) -> UpstreamOut:
    return await container.registry.get_upstream_out(upstream_id)


@router.patch("/upstreams/{upstream_id}", response_model=UpstreamOut)
async def update_upstream(
    upstream_id: uuid.UUID, payload: UpstreamUpdate, container: ContainerDep, _: AdminPrincipal
) -> UpstreamOut:
    upstream = await container.registry.update_upstream(upstream_id, payload)
    await container.pool.ensure(upstream)
    return await container.registry.get_upstream_out(upstream_id)


@router.delete("/upstreams/{upstream_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upstream(upstream_id: uuid.UUID, container: ContainerDep, _: AdminPrincipal) -> Response:
    await container.registry.delete_upstream(upstream_id)
    await container.pool.remove(upstream_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/upstreams/{upstream_id}/sync", response_model=SyncResult)
async def sync_upstream(upstream_id: uuid.UUID, container: ContainerDep, _: AdminPrincipal) -> SyncResult:
    return await container.sync.sync(upstream_id)


@router.get("/tools", response_model=Page[ToolSummary])
async def list_tools(
    container: ContainerDep,
    _: AdminPrincipal,
    filters: Annotated[ToolFilters, Depends()],
    page: Annotated[PageParams, Depends()],
) -> Page[ToolSummary]:
    return await container.registry.list_tools(filters, page)


@router.get("/tools/{tool_id}", response_model=ToolDetail)
async def get_tool(tool_id: uuid.UUID, container: ContainerDep, _: AdminPrincipal) -> ToolDetail:
    return await container.registry.tool_detail(tool_id)


@router.get("/tools/{tool_id}/diff", response_model=DefinitionDiff)
async def tool_diff(tool_id: uuid.UUID, container: ContainerDep, _: AdminPrincipal) -> DefinitionDiff:
    return await container.registry.diff(tool_id)


@router.post("/tools/{tool_id}/approve", response_model=ToolSummary)
async def approve_tool(
    tool_id: uuid.UUID, payload: ApproveRequest, container: ContainerDep, admin: AdminPrincipal
) -> ToolSummary:
    return await container.registry.approve(tool_id, payload.expected_hash, admin.subject, payload.note)


@router.post("/tools/{tool_id}/reject", response_model=ToolSummary)
async def reject_tool(
    tool_id: uuid.UUID, payload: RejectRequest, container: ContainerDep, admin: AdminPrincipal
) -> ToolSummary:
    return await container.registry.reject(tool_id, admin.subject, payload.reason)


@router.post("/tools/{tool_id}/rescan", response_model=ScanReport)
async def rescan_tool(tool_id: uuid.UUID, container: ContainerDep, _: AdminPrincipal) -> ScanReport:
    return await container.registry.rescan(tool_id)


@router.get("/approvals", response_model=list[ApprovalItem])
async def approval_queue(container: ContainerDep, _: AdminPrincipal) -> list[ApprovalItem]:
    return await container.registry.approval_queue()
