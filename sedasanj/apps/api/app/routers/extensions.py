from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import OrgAdminDep, TenantSession, UserDep
from app.errors import ApiError
from app.models import Call, Contact, PbxExtension, Tenant, User
from app.schemas import ExtensionOut, ExtensionUpdate
from app.services import audit, call_party_review, extensions

router = APIRouter(prefix="/v1/extensions", tags=["extensions"])


async def _out(
    session: AsyncSession,
    tenant_id: UUID,
    rows: list[PbxExtension],
    *,
    show_conflicts: bool = False,
) -> list[ExtensionOut]:
    contact_ids = {row.contact_id for row in rows if row.contact_id}
    user_ids = {row.user_id for row in rows if row.user_id}
    contact_names: dict[UUID, str] = {}
    user_names: dict[UUID, str] = {}
    if contact_ids:
        contact_names = dict(
            (
                await session.execute(
                    select(Contact.id, Contact.name).where(
                        Contact.tenant_id == tenant_id, Contact.id.in_(contact_ids)
                    )
                )
            ).all()  # type: ignore[arg-type]
        )
    if user_ids:
        user_names = {
            uid: display or email
            for uid, display, email in (
                await session.execute(
                    select(User.id, User.display_name, User.email).where(
                        User.tenant_id == tenant_id, User.id.in_(user_ids)
                    )
                )
            ).all()
        }
    claimed: dict[str, set[UUID]] = {}
    linked_elsewhere: set[UUID] = set()
    if show_conflicts and rows:
        operators = (
            await session.execute(
                select(User.id, User.extension).where(
                    User.tenant_id == tenant_id,
                    User.role == "operator",
                    User.extension.is_not(None),
                )
            )
        ).all()
        for operator_id, extension in operators:
            key = extensions.extension_key(extension)
            if key is not None:
                claimed.setdefault(key, set()).add(operator_id)
        linked_elsewhere = {
            user_id
            for user_id in (
                await session.scalars(
                    select(PbxExtension.user_id).where(
                        PbxExtension.tenant_id == tenant_id, PbxExtension.user_id.is_not(None)
                    )
                )
            ).all()
            if user_id is not None
        }

    def has_conflict(row: PbxExtension) -> bool:
        requested = claimed.get(row.extension, set())
        if row.user_id is not None:
            return bool(requested - {row.user_id})
        return not row.owner_managed and (len(requested) > 1 or bool(requested & linked_elsewhere))

    return [
        ExtensionOut(
            id=row.id,
            extension=row.extension,
            pbx_name=row.pbx_name,
            active=row.active,
            contact_id=row.contact_id,
            contact_name=contact_names.get(row.contact_id) if row.contact_id else None,
            user_id=row.user_id,
            user_name=user_names.get(row.user_id) if row.user_id else None,
            owner_conflict=has_conflict(row),
            synced_at=row.synced_at,
        )
        for row in rows
    ]


@router.get("", response_model=list[ExtensionOut])
async def list_extensions(
    principal: UserDep,
    session: TenantSession,
    include_inactive: Annotated[bool, Query()] = False,
) -> list[ExtensionOut]:
    assert principal.tenant_id is not None
    stmt = select(PbxExtension).where(PbxExtension.tenant_id == principal.tenant_id)
    if not include_inactive:
        stmt = stmt.where(PbxExtension.active.is_(True))
    rows = list((await session.execute(stmt.order_by(PbxExtension.extension))).scalars().all())
    rows.sort(key=lambda row: (len(row.extension), row.extension))
    return await _out(
        session, principal.tenant_id, rows, show_conflicts=principal.role == "org_admin"
    )


@router.get("/source")
async def extension_source(
    principal: OrgAdminDep, session: TenantSession
) -> dict[str, UUID | None]:
    assert principal.tenant_id is not None
    tenant = await session.get(Tenant, principal.tenant_id)
    return {"host_uuid": tenant.pbx_host_uuid if tenant else None}


@router.delete("/source/{host_uuid}", status_code=204)
async def reset_extension_source(
    host_uuid: UUID, principal: OrgAdminDep, session: TenantSession
) -> None:
    assert principal.tenant_id is not None
    await extensions.lock_inventory(session, principal.tenant_id)
    tenant = await session.get(Tenant, principal.tenant_id, populate_existing=True)
    if tenant is None or tenant.pbx_host_uuid != host_uuid:
        raise ApiError("conflict", "منبع همگام‌سازی تغییر کرده است؛ صفحه را تازه کنید")
    tenant.pbx_host_uuid = None


class RepairSelection(BaseModel):
    call_id: UUID
    token: str = Field(pattern=r"^[0-9a-f]{64}$")


class RepairBatch(BaseModel):
    items: list[RepairSelection] = Field(min_length=1, max_length=50)


@router.get("/review")
async def preview_repairs(
    principal: OrgAdminDep,
    session: TenantSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    started_from: datetime | None = None,
    started_before: datetime | None = None,
) -> dict[str, object]:
    stmt = select(Call).where(Call.tenant_id == principal.tenant_id)
    if started_from is not None:
        stmt = stmt.where(Call.started_at >= started_from)
    if started_before is not None:
        stmt = stmt.where(Call.started_at < started_before)
    rows = (
        await session.scalars(
            stmt.order_by(Call.started_at.desc(), Call.id).offset(offset).limit(limit + 1)
        )
    ).all()
    items = [(await call_party_review.preview(session, row))[0] for row in rows[:limit]]
    operator_ids = {
        operator_id
        for item in items
        for operator_id in (*item["operators"], *item["proposed_operators"])
    }
    operator_names = {}
    if operator_ids:
        operator_names = {
            str(user_id): name or email
            for user_id, name, email in (
                await session.execute(
                    select(User.id, User.display_name, User.email).where(
                        User.tenant_id == principal.tenant_id, User.id.in_(operator_ids)
                    )
                )
            ).all()
        }
    return {"items": items, "has_more": len(rows) > limit, "operator_names": operator_names}


@router.post("/review")
async def apply_repairs(
    payload: RepairBatch, principal: OrgAdminDep, session: TenantSession
) -> dict[str, list[UUID]]:
    assert principal.tenant_id is not None
    await extensions.lock_inventory(session, principal.tenant_id)
    applied: list[UUID] = []
    skipped: list[UUID] = []
    for item in sorted(payload.items, key=lambda item: item.call_id):
        call = await session.scalar(
            select(Call)
            .where(Call.id == item.call_id, Call.tenant_id == principal.tenant_id)
            .with_for_update()
        )
        result = await call_party_review.apply(session, call, item.token) if call else None
        if result is None:
            skipped.append(item.call_id)
            continue
        applied.append(item.call_id)
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="pbx.call_repair",
            payload={
                "call_id": str(item.call_id),
                "direction": result["direction"],
                "proposed_direction": result["proposed_direction"],
                "operators": [str(operator) for operator in result["operators"]],
                "proposed_operators": [str(operator) for operator in result["proposed_operators"]],
            },
        )
    return {"applied": applied, "skipped": skipped}


@router.patch("/{extension_id}", response_model=ExtensionOut)
async def update_extension(
    extension_id: UUID, payload: ExtensionUpdate, principal: OrgAdminDep, session: TenantSession
) -> ExtensionOut:
    assert principal.tenant_id is not None
    await extensions.lock_inventory(session, principal.tenant_id)
    row = (
        await session.execute(
            select(PbxExtension).where(
                PbxExtension.id == extension_id, PbxExtension.tenant_id == principal.tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "داخلی پیدا نشد؛ از ماژول FreePBX همگام‌سازی را دوباره بزنید")
    sent = payload.model_fields_set
    await extensions.assign(
        session,
        principal.tenant_id,
        row,
        contact_id=payload.contact_id,
        user_id=payload.user_id,
        set_contact="contact_id" in sent,
        set_user="user_id" in sent,
    )
    return (await _out(session, principal.tenant_id, [row], show_conflicts=True))[0]
