from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.deps import PublicSession, TenantSession, UserDep
from app.errors import ApiError
from app.models import CreditGrant, LedgerEntry, Package, Tenant
from app.schemas import BalanceOut, LedgerEntryOut, PackageOut
from app.services import billing

router = APIRouter(prefix="/v1/billing", tags=["billing"])


@router.get("/balance", response_model=BalanceOut)
async def get_balance(principal: UserDep, session: TenantSession) -> BalanceOut:
    if principal.role == "operator":
        raise ApiError("forbidden", "operators cannot view billing")
    assert principal.tenant_id is not None
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == principal.tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise ApiError("not_found", "tenant not found")
    balance = await billing.get_balance(session, principal.tenant_id)
    now = datetime.now(UTC)
    expiring_seconds = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(CreditGrant.remaining_seconds), 0)).where(
                    CreditGrant.tenant_id == principal.tenant_id,
                    CreditGrant.remaining_seconds > 0,
                    CreditGrant.expires_at > now,
                )
            )
        ).scalar_one()
    )
    purchased_seconds = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(CreditGrant.remaining_seconds), 0)).where(
                    CreditGrant.tenant_id == principal.tenant_id,
                    CreditGrant.remaining_seconds > 0,
                    CreditGrant.expires_at.is_(None),
                )
            )
        ).scalar_one()
    )
    next_expiration_at = (
        await session.execute(
            select(func.min(CreditGrant.expires_at)).where(
                CreditGrant.tenant_id == principal.tenant_id,
                CreditGrant.remaining_seconds > 0,
                CreditGrant.expires_at > now,
            )
        )
    ).scalar_one()
    return BalanceOut(
        seconds=balance.seconds,
        minutes=round(balance.seconds / 60, 1),
        toman=balance.toman,
        price_per_minute_toman=tenant.price_per_minute_toman,
        expiring_seconds=expiring_seconds,
        purchased_seconds=purchased_seconds,
        next_expiration_at=next_expiration_at,
    )


@router.get("/ledger")
async def get_ledger(
    principal: UserDep,
    session: TenantSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    if principal.role == "operator":
        raise ApiError("forbidden", "operators cannot view billing")
    total = int(
        (
            await session.execute(
                select(func.count(LedgerEntry.id)).where(
                    LedgerEntry.tenant_id == principal.tenant_id
                )
            )
        ).scalar_one()
    )
    rows = (
        await session.execute(
            select(LedgerEntry)
            .where(LedgerEntry.tenant_id == principal.tenant_id)
            .order_by(LedgerEntry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    items = [LedgerEntryOut.model_validate(row) for row in rows]
    return {"items": items, "total": total, "next_cursor": str(offset + limit) if offset + len(items) < total else None}


@router.get("/packages", response_model=list[PackageOut])
async def list_packages(session: PublicSession) -> list[PackageOut]:
    rows = (
        await session.execute(
            select(Package).where(Package.active.is_(True)).order_by(Package.minutes)
        )
    ).scalars()
    return [PackageOut.model_validate(row) for row in rows]
