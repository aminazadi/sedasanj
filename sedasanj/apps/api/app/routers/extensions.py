from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import OrgAdminDep, TenantSession, UserDep
from app.errors import ApiError
from app.models import Contact, PbxExtension, User
from app.schemas import ExtensionOut, ExtensionUpdate
from app.services import extensions

router = APIRouter(prefix="/v1/extensions", tags=["extensions"])


async def _out(
    session: AsyncSession, tenant_id: UUID, rows: list[PbxExtension]
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
    return await _out(session, principal.tenant_id, rows)


@router.patch("/{extension_id}", response_model=ExtensionOut)
async def update_extension(
    extension_id: UUID, payload: ExtensionUpdate, principal: OrgAdminDep, session: TenantSession
) -> ExtensionOut:
    assert principal.tenant_id is not None
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
    return (await _out(session, principal.tenant_id, [row]))[0]
