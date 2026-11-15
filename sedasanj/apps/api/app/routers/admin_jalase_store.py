"""Admin management of the Cafe Bazaar / Myket products sold for Jalase-Negar."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import StaffDep, StaffSession, SuperAdminDep, client_ip
from app.errors import ApiError
from app.models import Plan, StoreSku, TokenPackage
from app.services import audit

router = APIRouter(prefix="/v1/admin/jalase/store-skus", tags=["admin"])


class StoreSkuCreate(BaseModel):
    model_config = {"extra": "forbid"}
    store: Literal["bazaar", "myket"]
    sku: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,64}$")
    plan_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,32}$")
    package_id: UUID | None = None

    @model_validator(mode="after")
    def one_target(self) -> StoreSkuCreate:
        if (self.plan_code is None) == (self.package_id is None):
            raise ValueError("exactly one of plan_code and package_id is required")
        return self


class StoreSkuUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    active: bool


def _out(row: StoreSku) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "store": row.store,
        "sku": row.sku,
        "kind": row.kind,
        "plan_code": row.plan_code,
        "package_id": str(row.package_id) if row.package_id else None,
        "active": row.active,
    }


@router.get("")
async def list_store_skus(_: StaffDep, session: StaffSession) -> dict[str, Any]:
    rows = (
        (await session.execute(select(StoreSku).order_by(StoreSku.store, StoreSku.sku)))
        .scalars()
        .all()
    )
    plans = (
        await session.execute(
            select(Plan.code, Plan.name).where(Plan.product == "jalase_negar").order_by(Plan.code)
        )
    ).all()
    packs = (
        await session.execute(
            select(TokenPackage.id, TokenPackage.name, TokenPackage.tokens)
            .where(TokenPackage.product == "jalase_negar")
            .order_by(TokenPackage.tokens)
        )
    ).all()
    return {
        "items": [_out(row) for row in rows],
        "plans": [{"code": code, "name": name} for code, name in plans],
        "packs": [{"id": str(pid), "name": name, "tokens": tokens} for pid, name, tokens in packs],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_store_sku(
    payload: StoreSkuCreate, request: Request, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    if payload.plan_code is not None:
        plan = (
            await session.execute(
                select(Plan).where(Plan.code == payload.plan_code, Plan.product == "jalase_negar")
            )
        ).scalar_one_or_none()
        if plan is None:
            raise ApiError("plan_not_found", "این پلن جلسه‌نگار پیدا نشد؛ فهرست را تازه کنید.")
    else:
        package = await session.get(TokenPackage, payload.package_id)
        if package is None or package.product != "jalase_negar":
            raise ApiError("not_found", "این بستهٔ توکن جلسه‌نگار پیدا نشد؛ فهرست را تازه کنید.")
    row = StoreSku(
        store=payload.store,
        sku=payload.sku,
        kind="plan" if payload.plan_code else "pack",
        plan_code=payload.plan_code,
        package_id=payload.package_id,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError as error:
        raise ApiError("conflict_idempotency", "این شناسهٔ محصول قبلاً ثبت شده است.") from error
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="jalase_store_sku.created",
        payload={"store": row.store, "sku": row.sku, "kind": row.kind},
        ip=client_ip(request),
    )
    return _out(row)


@router.patch("/{sku_id}")
async def update_store_sku(
    sku_id: UUID,
    payload: StoreSkuUpdate,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, Any]:
    row = await session.get(StoreSku, sku_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "محصول پیدا نشد؛ صفحه را تازه کنید.")
    row.active = payload.active
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="jalase_store_sku.updated",
        payload={"store": row.store, "sku": row.sku, "active": row.active},
        ip=client_ip(request),
    )
    return _out(row)
