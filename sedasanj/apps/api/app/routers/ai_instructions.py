"""Custom AI instructions for the coach and meeting minutes: organization and staff editors."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.deps import OrgAdminDep, StaffDep, StaffSession, TenantSession, client_ip
from app.errors import ApiError
from app.models import Tenant
from app.services import audit, tenant_ai_instructions

router = APIRouter(tags=["ai instructions"])


class AiInstructionsOut(BaseModel):
    coach: str
    meeting: str
    max_chars: int = tenant_ai_instructions.MAX_INSTRUCTION_CHARS


class AiInstructionsIn(BaseModel):
    # Omitted scopes are left unchanged; an empty string removes that scope's instructions.
    coach: str | None = Field(default=None, max_length=100_000)
    meeting: str | None = Field(default=None, max_length=100_000)


async def _out(session: AsyncSession, tenant_id: UUID) -> AiInstructionsOut:
    values = await tenant_ai_instructions.get_all(session, tenant_id)
    return AiInstructionsOut(coach=values["coach"], meeting=values["meeting"])


async def _apply(
    session: AsyncSession,
    tenant_id: UUID,
    payload: AiInstructionsIn,
    *,
    actor_type: Literal["user", "staff"],
    actor_id: UUID | None,
) -> list[str]:
    changed: list[str] = []
    for scope in tenant_ai_instructions.SCOPES:
        value = getattr(payload, scope)
        if value is None:
            continue
        await tenant_ai_instructions.upsert(
            session, tenant_id, scope, value, actor_type=actor_type, actor_id=actor_id
        )
        changed.append(scope)
    return changed


@router.get("/v1/org/ai-instructions", response_model=AiInstructionsOut)
async def get_org_instructions(principal: OrgAdminDep, session: TenantSession) -> AiInstructionsOut:
    assert principal.tenant_id is not None
    return await _out(session, principal.tenant_id)


@router.put("/v1/org/ai-instructions", response_model=AiInstructionsOut)
async def put_org_instructions(
    payload: AiInstructionsIn, request: Request, principal: OrgAdminDep, session: TenantSession
) -> AiInstructionsOut:
    assert principal.tenant_id is not None
    changed = await _apply(
        session, principal.tenant_id, payload, actor_type="user", actor_id=principal.id
    )
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="org.ai_instructions_update",
        payload={"scopes": changed},
        ip=client_ip(request),
    )
    return await _out(session, principal.tenant_id)


@router.get("/v1/admin/tenants/{tenant_id}/ai-instructions", response_model=AiInstructionsOut)
async def get_tenant_instructions(
    tenant_id: UUID, staff: StaffDep, session: StaffSession
) -> AiInstructionsOut:
    if await session.get(Tenant, tenant_id) is None:
        raise ApiError("not_found", "tenant not found")
    async with session_scope(tenant_id) as tenant_session:
        return await _out(tenant_session, tenant_id)


@router.put("/v1/admin/tenants/{tenant_id}/ai-instructions", response_model=AiInstructionsOut)
async def put_tenant_instructions(
    tenant_id: UUID,
    payload: AiInstructionsIn,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> AiInstructionsOut:
    if await session.get(Tenant, tenant_id) is None:
        raise ApiError("not_found", "tenant not found")
    async with session_scope(tenant_id) as tenant_session:
        changed = await _apply(
            tenant_session, tenant_id, payload, actor_type="staff", actor_id=staff.id
        )
        values = await tenant_ai_instructions.get_all(tenant_session, tenant_id)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=tenant_id,
        action="tenant.ai_instructions_update",
        payload={"scopes": changed},
        ip=client_ip(request),
    )
    return AiInstructionsOut(coach=values["coach"], meeting=values["meeting"])
