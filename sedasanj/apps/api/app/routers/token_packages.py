"""LLM token packs: customers buy them through the normal order/payment flow."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import control_session_scope
from app.deps import OrgAdminDep, StaffSession, SuperAdminDep, TenantSession, client_ip
from app.errors import ApiError
from app.models import Order, OrderItem, TokenPackage, User
from app.services import audit, commerce
from app.services.commerce_settings import get_commerce_settings

router = APIRouter(prefix="/v1", tags=["token-packages"])


class TokenOrderCreate(BaseModel):
    package_id: UUID


class TokenPackageWrite(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    tokens: int = Field(ge=1_000, le=10_000_000_000)
    price_toman: int = Field(ge=1_000, le=2_000_000_000)
    active: bool = True


def _view(row: TokenPackage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "tokens": row.tokens,
        "price_toman": row.price_toman,
        "active": row.active,
    }


@router.get("/billing/token-packages")
async def token_packages(principal: OrgAdminDep) -> list[dict[str, Any]]:
    async with control_session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(TokenPackage)
                    .where(TokenPackage.active.is_(True))
                    .order_by(TokenPackage.tokens)
                )
            )
            .scalars()
            .all()
        )
    return [_view(row) for row in rows]


@router.post("/billing/token-orders", status_code=status.HTTP_201_CREATED)
async def create_token_order(
    payload: TokenOrderCreate,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> dict[str, Any]:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    existing = (
        await session.execute(
            select(Order).where(
                Order.tenant_id == tenant_id, Order.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"id": str(existing.id), "amount_toman": existing.amount_toman}
    async with control_session_scope() as control:
        package = await control.get(TokenPackage, payload.package_id)
        if package is None or not package.active:
            raise ApiError("not_found", "بسته توکن پیدا نشد؛ صفحه را تازه کنید.")
        tokens, amount, name = package.tokens, package.price_toman, package.name
    admin = await session.get(User, principal.id)
    assert admin is not None
    order = Order(
        tenant_id=tenant_id,
        number=f"TK-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(4).upper()}",
        kind="token_pack",
        status="draft",
        amount_toman=amount,
        callback_token=secrets.token_urlsafe(32),
        idempotency_key=idempotency_key,
        customer_name=admin.display_name or admin.email,
        customer_email=admin.email,
        customer_mobile=admin.mobile_number or "",
        invoice_profile={},
    )
    try:
        async with session.begin_nested():
            session.add(order)
            await session.flush()
    except IntegrityError:
        replay = (
            await session.execute(
                select(Order).where(
                    Order.tenant_id == tenant_id, Order.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if replay is None:
            raise
        return {"id": str(replay.id), "amount_toman": replay.amount_toman}
    session.add(
        OrderItem(
            order_id=order.id,
            tenant_id=tenant_id,
            kind="token_pack",
            description=f"بسته توکن هوش مصنوعی: {name}",
            quantity=tokens,
            unit_price_toman=amount,
            total_toman=amount,
            metadata_json={"package_id": str(payload.package_id)},
        )
    )
    await commerce.apply_tax(
        session, order, amount, (await get_commerce_settings(session)).tax_percent
    )
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=tenant_id,
        action="token_order.created",
        payload={"order_id": str(order.id), "tokens": tokens, "amount_toman": order.amount_toman},
        ip=client_ip(request),
    )
    return {"id": str(order.id), "amount_toman": order.amount_toman}


@router.get("/admin/token-packages")
async def admin_list_token_packages(
    _: SuperAdminDep, session: StaffSession
) -> list[dict[str, Any]]:
    rows = (await session.execute(select(TokenPackage).order_by(TokenPackage.tokens))).scalars()
    return [_view(row) for row in rows]


@router.post("/admin/token-packages", status_code=status.HTTP_201_CREATED)
async def admin_create_token_package(
    payload: TokenPackageWrite, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    row = TokenPackage(**payload.model_dump())
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="token_package.created",
        payload={"package_id": str(row.id), "tokens": row.tokens},
    )
    return _view(row)


@router.patch("/admin/token-packages/{package_id}")
async def admin_update_token_package(
    package_id: UUID, payload: TokenPackageWrite, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    row = await session.get(TokenPackage, package_id)
    if row is None:
        raise ApiError("not_found", "بسته توکن پیدا نشد.")
    row.name, row.tokens = payload.name, payload.tokens
    row.price_toman, row.active = payload.price_toman, payload.active
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="token_package.updated",
        payload={"package_id": str(row.id)},
    )
    return _view(row)
