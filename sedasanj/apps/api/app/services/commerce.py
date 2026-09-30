from __future__ import annotations

import calendar
import math
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Order, OrderItem, Plan, PlanVersion, Tenant


def add_months(value: datetime, months: int) -> datetime:
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


async def public_plans(session: AsyncSession) -> list[tuple[Plan, PlanVersion]]:
    now = datetime.now(UTC)
    rows = await session.execute(
        select(Plan, PlanVersion)
        .join(PlanVersion, PlanVersion.plan_id == Plan.id)
        .where(
            Plan.active.is_(True),
            Plan.public.is_(True),
            PlanVersion.status == "published",
            PlanVersion.effective_at.is_not(None),
            PlanVersion.effective_at <= now,
        )
        .order_by(Plan.sort_order)
    )
    all_rows = rows.all()
    versions: dict[UUID, tuple[Plan, PlanVersion]] = {}
    for plan, version in all_rows:
        current = versions.get(plan.id)
        if current is None or version.version > current[1].version:
            versions[plan.id] = (plan, version)
    return list(versions.values())


async def plan_version_by_code(session: AsyncSession, code: str) -> tuple[Plan, PlanVersion]:
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(Plan, PlanVersion)
            .join(PlanVersion, PlanVersion.plan_id == Plan.id)
            .where(
                Plan.code == code,
                Plan.active.is_(True),
                PlanVersion.status == "published",
                PlanVersion.effective_at.is_not(None),
                PlanVersion.effective_at <= now,
            )
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        raise ApiError("not_found", "plan not found")
    return row[0], row[1]


def subscription_amount(version: PlanVersion, period: str, extra_operators: int) -> tuple[int, int]:
    if period not in {"monthly", "annual"}:
        raise ApiError("invalid_request", "billing period is invalid")
    if extra_operators < 0 or (extra_operators and not version.allows_extra_operators):
        raise ApiError("invalid_request", "extra operators are not available for this plan")
    base = version.monthly_price_toman if period == "monthly" else version.annual_price_toman
    extra_unit = (
        version.extra_operator_monthly_toman
        if period == "monthly"
        else version.extra_operator_annual_toman
    )
    if base is None or (extra_operators and extra_unit is None):
        raise ApiError("invalid_request", "selected billing period is unavailable")
    return base + extra_operators * (extra_unit or 0), extra_unit or 0


async def create_subscription_order(
    session: AsyncSession,
    *,
    tenant: Tenant,
    plan_code: str,
    period: str,
    extra_operators: int,
    customer_name: str,
    customer_email: str,
    customer_mobile: str,
    invoice_profile: dict[str, object],
    idempotency_key: str,
) -> Order:
    existing = (
        await session.execute(
            select(Order).where(
                Order.tenant_id == tenant.id, Order.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    plan, version = await plan_version_by_code(session, plan_code)
    if plan.code == "demo":
        raise ApiError("invalid_request", "demo does not require payment")
    total, extra_unit = subscription_amount(version, period, extra_operators)
    order = Order(
        tenant_id=tenant.id,
        number=f"SS-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(4).upper()}",
        kind="subscription",
        status="draft",
        amount_toman=total,
        callback_token=secrets.token_urlsafe(32),
        idempotency_key=idempotency_key,
        customer_name=customer_name.strip(),
        customer_email=customer_email.strip().lower(),
        customer_mobile=customer_mobile,
        invoice_profile=invoice_profile,
    )
    session.add(order)
    await session.flush()
    session.add(
        OrderItem(
            order_id=order.id,
            tenant_id=tenant.id,
            kind="subscription",
            description=f"اشتراک {plan.name} - {'سالانه' if period == 'annual' else 'ماهانه'}",
            quantity=1,
            unit_price_toman=total - extra_operators * extra_unit,
            total_toman=total - extra_operators * extra_unit,
            metadata_json={"plan_code": plan.code, "plan_version_id": str(version.id), "billing_period": period},
        )
    )
    if extra_operators:
        session.add(
            OrderItem(
                order_id=order.id,
                tenant_id=tenant.id,
                kind="extra_operator",
                description="اپراتور اضافه پلن طلایی",
                quantity=extra_operators,
                unit_price_toman=extra_unit,
                total_toman=extra_operators * extra_unit,
                metadata_json={},
            )
        )
    return order


def prorated_amount(full_amount: int, period_start: datetime, period_end: datetime, now: datetime) -> int:
    total = max(1, int((period_end - period_start).total_seconds()))
    remaining = max(0, int((period_end - now).total_seconds()))
    return math.ceil(full_amount * remaining / total)
