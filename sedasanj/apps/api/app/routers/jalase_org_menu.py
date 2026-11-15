"""Panel menu of Jalase-Negar document categories an organization actually has documents in."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import select

from app.db import control_session_scope
from app.deps import OrgAdminDep, TenantSession, UserDep
from app.errors import ApiError
from app.models import JalaseMenuHidden, JalaseOutputType, MeetingDocument

router = APIRouter(prefix="/v1/jalase/org-menu", tags=["jalase-menu"])


class HiddenUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    hidden: bool


@router.get("")
async def menu(principal: UserDep, session: TenantSession) -> dict[str, Any]:
    """Categories with at least one document, minus the ones an admin hid.

    A category appears with its first document, so the menu never lists empty entries.
    """
    assert principal.tenant_id is not None
    codes = set(
        (
            await session.execute(
                select(MeetingDocument.output_type_code)
                .where(
                    MeetingDocument.tenant_id == principal.tenant_id,
                    MeetingDocument.status != "purged",
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    hidden = set(
        (
            await session.execute(
                select(JalaseMenuHidden.output_type_code).where(
                    JalaseMenuHidden.tenant_id == principal.tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not codes:
        return {"items": [], "hidden": sorted(hidden)}
    async with control_session_scope() as control:
        types = (
            (
                await control.execute(
                    select(JalaseOutputType)
                    .where(JalaseOutputType.code.in_(codes))
                    .order_by(JalaseOutputType.sort_order, JalaseOutputType.code)
                )
            )
            .scalars()
            .all()
        )
    items = [
        {
            "code": t.code,
            "label": t.menu_label_fa,
            "thumbnail_media_id": str(t.thumbnail_media_id) if t.thumbnail_media_id else None,
            "hidden": t.code in hidden,
        }
        for t in types
    ]
    return {
        "items": [i for i in items if not i["hidden"]],
        "hidden": [i["code"] for i in items if i["hidden"]],
    }


@router.put("/{code}/hidden", status_code=status.HTTP_204_NO_CONTENT)
async def set_hidden(
    code: str, payload: HiddenUpdate, principal: OrgAdminDep, session: TenantSession
) -> None:
    """Hide or show one category in this organization's panel menu (org admins only)."""
    assert principal.tenant_id is not None
    async with control_session_scope() as control:
        known = (
            await control.execute(select(JalaseOutputType.id).where(JalaseOutputType.code == code))
        ).first()
    if known is None:
        raise ApiError("output_type_not_found", "این دسته پیدا نشد؛ صفحه را تازه کنید.")
    row = await session.get(JalaseMenuHidden, (principal.tenant_id, code))
    if payload.hidden and row is None:
        session.add(JalaseMenuHidden(tenant_id=principal.tenant_id, output_type_code=code))
    elif not payload.hidden and row is not None:
        await session.delete(row)
