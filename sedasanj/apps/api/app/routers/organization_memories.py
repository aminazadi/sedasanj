from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import OrgAdminDep, TenantSession, client_ip
from app.errors import ApiError
from app.models import OrganizationMemory
from app.schemas import (
    OrganizationMemoryAction,
    OrganizationMemoryMerge,
    OrganizationMemoryOut,
    OrganizationMemoryUpdate,
)
from app.services import audit, organization_memory

router = APIRouter(prefix="/v1/assistant/memories", tags=["organization memory"])


async def _row(session: AsyncSession, tenant_id: UUID, memory_id: UUID, *, lock: bool = False) -> OrganizationMemory:
    query = select(OrganizationMemory).where(
        OrganizationMemory.id == memory_id, OrganizationMemory.tenant_id == tenant_id
    )
    if lock:
        query = query.with_for_update()
    row = (await session.execute(query)).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "organization memory not found")
    return row


async def _out(session: AsyncSession, row: OrganizationMemory) -> OrganizationMemoryOut:
    active = (
        await session.execute(
            select(OrganizationMemory).where(
                OrganizationMemory.tenant_id == row.tenant_id,
                OrganizationMemory.status == "active",
            )
        )
    ).scalars().all()
    values = organization_memory.conflicts(row, list(active)) if row.status == "draft" else []
    return OrganizationMemoryOut.model_validate(row).model_copy(
        update={"conflicts": [item.id for item in values]}
    )


def _check_lock(row: OrganizationMemory, lock_version: int) -> None:
    if row.lock_version != lock_version:
        raise ApiError("conflict_idempotency", "organization memory changed; reload and retry")


@router.get("", response_model=list[OrganizationMemoryOut])
async def list_memories(
    principal: OrgAdminDep,
    session: TenantSession,
    memory_status: str | None = Query(default=None, alias="status"),
    category: str | None = None,
) -> list[OrganizationMemoryOut]:
    query = select(OrganizationMemory).where(OrganizationMemory.tenant_id == principal.tenant_id)
    if memory_status:
        query = query.where(OrganizationMemory.status == memory_status)
    if category:
        query = query.where(OrganizationMemory.category == category)
    rows = (await session.execute(query.order_by(OrganizationMemory.updated_at.desc()))).scalars().all()
    return [await _out(session, row) for row in rows]


@router.get("/export")
async def export_memories(principal: OrgAdminDep, session: TenantSession) -> Response:
    rows = (
        await session.execute(
            select(OrganizationMemory)
            .where(OrganizationMemory.tenant_id == principal.tenant_id)
            .order_by(OrganizationMemory.logical_key, OrganizationMemory.version)
        )
    ).scalars().all()
    return Response(
        organization_memory.export_payload(list(rows)),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="organization-memories.json"'},
    )


@router.post("/preview-context")
async def preview_context(
    principal: OrgAdminDep,
    session: TenantSession,
    scope: str = Query(pattern="^(assistant|correction|analysis|scoring)$"),
) -> dict[str, object]:
    context = await organization_memory.build_context(session, principal.tenant_id, scope)
    return {"context": context.text, "snapshot": context.snapshot, "sha256": context.sha256}


@router.get("/{memory_id}", response_model=OrganizationMemoryOut)
async def get_memory(memory_id: UUID, principal: OrgAdminDep, session: TenantSession) -> OrganizationMemoryOut:
    return await _out(session, await _row(session, principal.tenant_id, memory_id))


@router.get("/{logical_key}/versions", response_model=list[OrganizationMemoryOut])
async def memory_versions(logical_key: str, principal: OrgAdminDep, session: TenantSession) -> list[OrganizationMemoryOut]:
    rows = (
        await session.execute(
            select(OrganizationMemory)
            .where(
                OrganizationMemory.tenant_id == principal.tenant_id,
                OrganizationMemory.logical_key == logical_key,
            )
            .order_by(OrganizationMemory.version.desc())
        )
    ).scalars().all()
    return [await _out(session, row) for row in rows]


@router.patch("/{memory_id}/draft", response_model=OrganizationMemoryOut)
async def update_draft(
    memory_id: UUID,
    payload: OrganizationMemoryUpdate,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
) -> OrganizationMemoryOut:
    row = await _row(session, principal.tenant_id, memory_id, lock=True)
    _check_lock(row, payload.lock_version)
    values = payload.model_dump(exclude_none=True, exclude={"lock_version"})
    if row.status == "active":
        latest_version = int(
            (
                await session.execute(
                    select(func.max(OrganizationMemory.version)).where(
                        OrganizationMemory.tenant_id == principal.tenant_id,
                        OrganizationMemory.logical_key == row.logical_key,
                    )
                )
            ).scalar_one()
            or 0
        )
        row = OrganizationMemory(
            tenant_id=principal.tenant_id,
            logical_key=row.logical_key,
            version=latest_version + 1,
            supersedes_id=row.id,
            category=str(values.get("category", row.category)),
            title=str(values.get("title", row.title)),
            content=str(values.get("content", row.content)),
            structured_payload=values.get("structured_payload", row.structured_payload),
            tags=values.get("tags", row.tags),
            applies_to=values.get("applies_to", row.applies_to),
            status="draft",
            created_by=principal.id,
        )
        session.add(row)
    elif row.status != "draft":
        raise ApiError("invalid_request", "only draft or active memories can be edited")
    for key, value in values.items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    try:
        organization_memory.validate_fields(row.category, row.applies_to, row.title, row.content)
    except ValueError as exc:
        raise ApiError("invalid_request", str(exc)) from exc
    row.lock_version += 1
    row.updated_at = datetime.now(UTC)
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="assistant.memory_draft_update", payload={"memory_id": str(row.id)}, ip=client_ip(request))
    await session.flush()
    return await _out(session, row)


async def _idempotent(session: AsyncSession, tenant_id: UUID, key: str | None) -> OrganizationMemory | None:
    if not key:
        return None
    return (
        await session.execute(
            select(OrganizationMemory).where(
                OrganizationMemory.tenant_id == tenant_id,
                OrganizationMemory.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()


@router.post("/{memory_id}/approve", response_model=OrganizationMemoryOut)
async def approve_memory(memory_id: UUID, payload: OrganizationMemoryAction, request: Request, principal: OrgAdminDep, session: TenantSession) -> OrganizationMemoryOut:
    existing = await _idempotent(session, principal.tenant_id, payload.idempotency_key)
    if existing:
        return await _out(session, existing)
    row = await _row(session, principal.tenant_id, memory_id, lock=True)
    _check_lock(row, payload.lock_version)
    if row.status != "draft":
        raise ApiError("invalid_request", "only draft memories can be approved")
    active = (
        await session.execute(
            select(OrganizationMemory).where(
                OrganizationMemory.tenant_id == principal.tenant_id,
                OrganizationMemory.logical_key == row.logical_key,
                OrganizationMemory.status == "active",
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        raise ApiError("conflict_idempotency", "an active version exists; use replace or merge")
    count = int((await session.execute(select(func.count()).select_from(OrganizationMemory).where(OrganizationMemory.tenant_id == principal.tenant_id, OrganizationMemory.status == "active"))).scalar_one())
    if count >= organization_memory.MAX_ACTIVE_MEMORIES:
        raise ApiError("invalid_request", "active organization memory limit reached")
    now = datetime.now(UTC)
    row.status = "active"
    row.approved_by = principal.id
    row.approved_at = now
    row.updated_at = now
    row.idempotency_key = payload.idempotency_key
    row.lock_version += 1
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="assistant.memory_approve", payload={"memory_id": str(row.id)}, ip=client_ip(request))
    await session.flush()
    return await _out(session, row)


@router.post("/{memory_id}/reject", response_model=OrganizationMemoryOut)
async def reject_memory(memory_id: UUID, payload: OrganizationMemoryAction, request: Request, principal: OrgAdminDep, session: TenantSession) -> OrganizationMemoryOut:
    row = await _row(session, principal.tenant_id, memory_id, lock=True)
    _check_lock(row, payload.lock_version)
    if row.status != "draft":
        raise ApiError("invalid_request", "only draft memories can be rejected")
    row.status = "rejected"
    row.lock_version += 1
    row.updated_at = datetime.now(UTC)
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="assistant.memory_reject", payload={"memory_id": str(row.id)}, ip=client_ip(request))
    await session.flush()
    return await _out(session, row)


@router.post("/{memory_id}/replace", response_model=OrganizationMemoryOut)
async def replace_memory(memory_id: UUID, payload: OrganizationMemoryAction, request: Request, principal: OrgAdminDep, session: TenantSession) -> OrganizationMemoryOut:
    existing = await _idempotent(session, principal.tenant_id, payload.idempotency_key)
    if existing:
        return await _out(session, existing)
    draft = await _row(session, principal.tenant_id, memory_id, lock=True)
    _check_lock(draft, payload.lock_version)
    if draft.status != "draft":
        raise ApiError("invalid_request", "replacement must be a draft")
    current = (
        await session.execute(
            select(OrganizationMemory).where(
                OrganizationMemory.tenant_id == principal.tenant_id,
                OrganizationMemory.logical_key == draft.logical_key,
                OrganizationMemory.status == "active",
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if current is None:
        active_rows = list(
            (
                await session.execute(
                    select(OrganizationMemory)
                    .where(
                        OrganizationMemory.tenant_id == principal.tenant_id,
                        OrganizationMemory.status == "active",
                    )
                    .with_for_update()
                )
            ).scalars().all()
        )
        candidates = organization_memory.conflicts(draft, active_rows)
        current = candidates[0] if candidates else None
    if current is None:
        raise ApiError("conflict_idempotency", "active memory to replace was not found")
    now = datetime.now(UTC)
    current.status = "superseded"
    current.lock_version += 1
    current.updated_at = now
    draft.logical_key = current.logical_key
    latest_version = int(
        (
            await session.execute(
                select(func.max(OrganizationMemory.version)).where(
                    OrganizationMemory.tenant_id == principal.tenant_id,
                    OrganizationMemory.logical_key == current.logical_key,
                )
            )
        ).scalar_one()
        or 0
    )
    draft.version = latest_version + 1
    draft.supersedes_id = current.id
    draft.status = "active"
    draft.approved_by = principal.id
    draft.approved_at = now
    draft.updated_at = now
    draft.idempotency_key = payload.idempotency_key
    draft.lock_version += 1
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="assistant.memory_replace", payload={"memory_id": str(draft.id), "replaced_id": str(current.id)}, ip=client_ip(request))
    await session.flush()
    return await _out(session, draft)


@router.post("/merge", response_model=OrganizationMemoryOut, status_code=status.HTTP_201_CREATED)
async def merge_memories(payload: OrganizationMemoryMerge, request: Request, principal: OrgAdminDep, session: TenantSession) -> OrganizationMemoryOut:
    existing = await _idempotent(session, principal.tenant_id, payload.idempotency_key)
    if existing:
        return await _out(session, existing)
    rows = list((await session.execute(select(OrganizationMemory).where(OrganizationMemory.tenant_id == principal.tenant_id, OrganizationMemory.id.in_(payload.memory_ids)).with_for_update())).scalars().all())
    if len(rows) != len(set(payload.memory_ids)):
        raise ApiError("not_found", "one or more organization memories were not found")
    for row in rows:
        _check_lock(row, payload.lock_versions.get(row.id, 0))
        if row.status not in {"active", "draft"}:
            raise ApiError("invalid_request", "only active or draft memories can be merged")
    try:
        organization_memory.validate_fields(payload.category, list(payload.applies_to), payload.title, payload.content)
    except ValueError as exc:
        raise ApiError("invalid_request", str(exc)) from exc
    now = datetime.now(UTC)
    for row in rows:
        row.status = "superseded"
        row.lock_version += 1
        row.updated_at = now
    latest = max(rows, key=lambda row: row.version)
    logical_key = organization_memory.normalize_key(payload.logical_key)
    next_version = int(
        (
            await session.execute(
                select(func.max(OrganizationMemory.version)).where(
                    OrganizationMemory.tenant_id == principal.tenant_id,
                    OrganizationMemory.logical_key == logical_key,
                )
            )
        ).scalar_one()
        or 0
    ) + 1
    merged = OrganizationMemory(
        tenant_id=principal.tenant_id, logical_key=logical_key,
        version=next_version, supersedes_id=latest.id, category=payload.category,
        title=payload.title.strip(), content=payload.content.strip(), structured_payload=payload.structured_payload,
        tags=list(dict.fromkeys(tag.strip() for tag in payload.tags if tag.strip())), applies_to=list(dict.fromkeys(payload.applies_to)),
        status="active", created_by=principal.id, approved_by=principal.id, approved_at=now,
        idempotency_key=payload.idempotency_key,
    )
    session.add(merged)
    await session.flush()
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="assistant.memory_merge", payload={"memory_id": str(merged.id), "merged_ids": [str(row.id) for row in rows]}, ip=client_ip(request))
    return await _out(session, merged)


@router.post("/{memory_id}/archive", response_model=OrganizationMemoryOut)
async def archive_memory(memory_id: UUID, payload: OrganizationMemoryAction, request: Request, principal: OrgAdminDep, session: TenantSession) -> OrganizationMemoryOut:
    row = await _row(session, principal.tenant_id, memory_id, lock=True)
    _check_lock(row, payload.lock_version)
    if row.status not in {"active", "draft"}:
        raise ApiError("invalid_request", "memory cannot be archived from its current state")
    row.status = "archived"
    row.archived_at = datetime.now(UTC)
    row.updated_at = row.archived_at
    row.lock_version += 1
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="assistant.memory_archive", payload={"memory_id": str(row.id)}, ip=client_ip(request))
    await session.flush()
    return await _out(session, row)
