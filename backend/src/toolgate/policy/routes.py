from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from toolgate.auth.dependencies import AdminPrincipal
from toolgate.container import Container, get_container
from toolgate.policy.evaluator import Decision
from toolgate.policy.schemas import Policy, PolicyCreate, PolicyUpdate, SimulationRequest

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])
ContainerDep = Annotated[Container, Depends(get_container)]


@router.get("", response_model=list[Policy])
async def list_policies(container: ContainerDep, _: AdminPrincipal) -> list[Policy]:
    return await container.policies.list()


@router.post("", response_model=Policy, status_code=status.HTTP_201_CREATED)
async def create_policy(payload: PolicyCreate, container: ContainerDep, _: AdminPrincipal) -> Policy:
    return await container.policies.create(payload)


@router.post("/simulate", response_model=Decision)
async def simulate(payload: SimulationRequest, container: ContainerDep, _: AdminPrincipal) -> Decision:
    container.policies.invalidate()
    return await container.policies.simulate(payload)


@router.get("/{policy_id}", response_model=Policy)
async def get_policy(policy_id: uuid.UUID, container: ContainerDep, _: AdminPrincipal) -> Policy:
    return await container.policies.get(policy_id)


@router.put("/{policy_id}", response_model=Policy)
async def update_policy(
    policy_id: uuid.UUID, payload: PolicyUpdate, container: ContainerDep, _: AdminPrincipal
) -> Policy:
    return await container.policies.update(policy_id, payload)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: uuid.UUID, container: ContainerDep, _: AdminPrincipal) -> Response:
    await container.policies.delete(policy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
