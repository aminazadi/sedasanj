"""Link a personal Jalase-Negar account to a SedaSanj organization.

The app keeps two keys: the personal one and an organization device key made from the
organization's normal pairing code.  This module records that link (so it can be listed and
revoked) and never moves data: meetings sent with the organization key are the organization's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import ApiKey, JalaseAccountLink, Tenant
from app.routers.meetings import redeem_pairing_code
from app.schemas import MeetingPairIn
from app.services import audit

PRODUCT = "jalase_negar"


async def link(
    session: AsyncSession,
    *,
    personal_tenant_id: UUID,
    personal_user_id: UUID,
    payload: MeetingPairIn,
    ip: str | None,
) -> dict[str, Any]:
    """Redeem an organization pairing code for this personal account."""
    personal = await session.get(Tenant, personal_tenant_id)
    if personal is None or personal.product != PRODUCT:
        raise ApiError("forbidden", "این بخش فقط برای حساب شخصی جلسه‌نگار است.")
    try:
        async with session.begin_nested():
            out, key_id, org_tenant_id, org_user_id = await redeem_pairing_code(
                session, payload, ip
            )
            org = await session.get(Tenant, org_tenant_id)
            if org is None or org.product == PRODUCT:
                raise ApiError(
                    "link_invalid_target",
                    "این کد مربوط به یک سازمان صداسنج نیست؛ کد را از پنل سازمان بگیرید.",
                )
            row = JalaseAccountLink(
                personal_tenant_id=personal_tenant_id,
                personal_user_id=personal_user_id,
                org_tenant_id=org_tenant_id,
                org_user_id=org_user_id,
                org_api_key_id=key_id,
            )
            session.add(row)
            await session.flush()
    except IntegrityError as error:
        raise ApiError(
            "link_already_exists",
            "این حساب قبلاً به همین سازمان وصل است؛ اتصال قبلی را قطع کنید و دوباره وصل شوید.",
        ) from error
    await audit.record(
        session,
        actor_type="user",
        actor_id=personal_user_id,
        tenant_id=personal_tenant_id,
        action="jalase.link.created",
        payload={"link_id": str(row.id), "org_tenant_id": str(org_tenant_id)},
        ip=ip,
    )
    return {
        "link_id": str(row.id),
        "token": out.token,
        "token_prefix": out.token_prefix,
        "organization": out.tenant.name,
        "user": out.user.display_name,
    }


async def list_links(session: AsyncSession, personal_tenant_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(JalaseAccountLink, Tenant.name)
            .join(Tenant, Tenant.id == JalaseAccountLink.org_tenant_id)
            .where(
                JalaseAccountLink.personal_tenant_id == personal_tenant_id,
                JalaseAccountLink.status == "active",
            )
            .order_by(JalaseAccountLink.linked_at)
        )
    ).all()
    return [
        {"id": str(row.id), "organization": name, "linked_at": row.linked_at} for row, name in rows
    ]


async def revoke(
    session: AsyncSession, personal_tenant_id: UUID, personal_user_id: UUID, link_id: UUID
) -> None:
    """Revoke the organization key. Data stays where it was made."""
    row = (
        await session.execute(
            select(JalaseAccountLink)
            .where(
                JalaseAccountLink.id == link_id,
                JalaseAccountLink.personal_tenant_id == personal_tenant_id,
                JalaseAccountLink.status == "active",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("link_not_found", "این اتصال پیدا نشد یا قبلاً قطع شده است.")
    now = datetime.now(UTC)
    key = await session.get(ApiKey, row.org_api_key_id, with_for_update=True)
    if key is not None and key.revoked_at is None:
        key.revoked_at = now
    row.status = "revoked"
    row.revoked_at = now
    await audit.record(
        session,
        actor_type="user",
        actor_id=personal_user_id,
        tenant_id=personal_tenant_id,
        action="jalase.link.revoked",
        payload={"link_id": str(link_id)},
    )
