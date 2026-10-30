from __future__ import annotations

import calendar
import math
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Order, OrderItem, Plan, PlanVersion, Subscription, Tenant
from app.services.commerce_settings import get_commerce_settings


def add_months(value: datetime, months: int) -> datetime:
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def tax_for(net: int, percent: int) -> int:
    """Tax on a net amount, rounded half up to a whole toman."""
    return (net * percent + 50) // 100


async def apply_tax(session: AsyncSession, order: Order, net: int, percent: int) -> int:
    """Set the payable total (net + tax) and add the tax line; returns the tax amount."""
    tax = tax_for(net, percent)
    order.amount_toman = net + tax
    if tax:
        session.add(
            OrderItem(
                order_id=order.id,
                tenant_id=order.tenant_id,
                kind="tax",
                description=f"مالیات بر ارزش افزوده ({percent}٪)",
                quantity=1,
                unit_price_toman=tax,
                total_toman=tax,
                metadata_json={"percent": percent},
            )
        )
    return tax


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


async def _reject_plan_switch_by_purchase(
    session: AsyncSession, tenant_id: UUID, plan: Plan
) -> None:
    """A running paid plan changes through /subscription/change, never by buying another plan."""
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(Plan.id, Plan.code)
            .join(PlanVersion, PlanVersion.plan_id == Plan.id)
            .join(Subscription, Subscription.plan_version_id == PlanVersion.id)
            .where(
                Subscription.tenant_id == tenant_id,
                Subscription.status == "active",
                Subscription.billing_period != "trial",
                Subscription.period_end > now,
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is not None and row[0] != plan.id:
        raise ApiError(
            "subscription_exists",
            "an active paid plan already exists; change plan from the subscription page",
        )


def subscription_amount(version: PlanVersion, period: str, extra_operators: int) -> tuple[int, int]:
    if period != "annual":
        raise ApiError("invalid_request", "billing period is invalid")
    if extra_operators < 0 or (extra_operators and not version.allows_extra_operators):
        raise ApiError("invalid_request", "extra operators are not available for this plan")
    base = version.annual_price_toman
    extra_unit = version.extra_operator_annual_toman
    if base is None or (extra_operators and extra_unit is None):
        raise ApiError("invalid_request", "selected billing period is unavailable")
    effective_extra_unit = (extra_unit or 0) if version.allows_extra_operators else 0
    return base + extra_operators * effective_extra_unit, effective_extra_unit


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
    if plan.is_trial:
        raise ApiError("invalid_request", "a trial plan does not require payment")
    if not plan.sellable:
        raise ApiError("plan_not_sellable", "this plan is not available for purchase")
    await _reject_plan_switch_by_purchase(session, tenant.id, plan)
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
    try:
        async with session.begin_nested():
            session.add(order)
            await session.flush()
    except IntegrityError:
        # A concurrent request with the same idempotency key won the race: replay it.
        replay = (
            await session.execute(
                select(Order).where(
                    Order.tenant_id == tenant.id, Order.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if replay is None:
            raise
        return replay
    session.add(
        OrderItem(
            order_id=order.id,
            tenant_id=tenant.id,
            kind="subscription",
            description=f"اشتراک {plan.name} - سالانه",
            quantity=1,
            unit_price_toman=total - extra_operators * extra_unit,
            total_toman=total - extra_operators * extra_unit,
            metadata_json={
                "plan_code": plan.code,
                "plan_version_id": str(version.id),
                "billing_period": period,
            },
        )
    )
    if extra_operators:
        session.add(
            OrderItem(
                order_id=order.id,
                tenant_id=tenant.id,
                kind="extra_operator",
                description=f"اپراتور اضافه {plan.name}",
                quantity=extra_operators,
                unit_price_toman=extra_unit,
                total_toman=extra_operators * extra_unit,
                metadata_json={"plan_code": plan.code},
            )
        )
    await apply_tax(session, order, total, (await get_commerce_settings(session)).tax_percent)
    return order


def annual_window(
    period_start: datetime, period_end: datetime, now: datetime
) -> tuple[datetime, datetime]:
    """The paid year containing ``now``; early renewals stack whole years on one anniversary."""
    years = 0
    while (
        add_months(period_start, 12 * (years + 1)) <= now
        and add_months(period_start, 12 * (years + 1)) < period_end
    ):
        years += 1
    start = add_months(period_start, 12 * years)
    return start, min(add_months(start, 12), period_end)


def prorated_amount(
    full_amount: int, period_start: datetime, period_end: datetime, now: datetime
) -> int:
    window_start, window_end = annual_window(period_start, period_end, now)
    total = max(1, int((window_end - window_start).total_seconds()))
    remaining = max(0, int((window_end - now).total_seconds()))
    return math.ceil(full_amount * remaining / total)
