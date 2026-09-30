from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Subscription
from app.services import billing


@dataclass(frozen=True)
class Entitlements:
    subscription_id: UUID | None
    status: str
    max_operators: int
    price_per_minute_toman: int
    assistant_tier: str
    assistant_monthly_messages: int
    assistant_source_limit: int
    assistant_model: str | None
    period_start: datetime | None
    period_end: datetime | None

    @property
    def consumption_allowed(self) -> bool:
        return self.status in {"active", "trialing"} and bool(
            self.period_end and self.period_end > datetime.now(UTC)
        )


async def effective(session: AsyncSession, tenant_id: UUID, *, lock: bool = False) -> Entitlements:
    stmt = (
        select(Subscription)
        .where(
            Subscription.tenant_id == tenant_id,
            Subscription.status.in_(("active", "trialing", "pending_payment", "expired")),
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return Entitlements(None, "missing", 0, 2000, "none", 0, 0, None, None, None)
    status = row.status
    if status in {"active", "trialing"} and row.period_end <= datetime.now(UTC):
        row.status = "expired"
        row.updated_at = datetime.now(UTC)
        status = "expired"
    return Entitlements(
        row.id,
        status,
        row.base_operators + row.extra_operators,
        row.price_per_minute_toman,
        row.assistant_tier,
        row.assistant_monthly_messages,
        row.assistant_source_limit,
        row.assistant_model,
        row.period_start,
        row.period_end,
    )


async def require_consumption(session: AsyncSession, tenant_id: UUID) -> Entitlements:
    value = await effective(session, tenant_id)
    if not value.consumption_allowed:
        raise ApiError("quota_exceeded", "subscription is not active")
    return value


async def require_upload_consumption(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    price_per_minute_toman: int,
) -> Entitlements:
    """Allow audio processing when the tenant has an active plan or prepaid credit.

    A prepaid credit purchase is independently billable by ``billing.reserve``;
    it must not be rejected merely because the tenant has not bought a plan.
    Plan-only limits (for example, operator seats) continue to use
    ``require_consumption``.
    """
    value = await effective(session, tenant_id)
    if value.consumption_allowed:
        return value
    balance = await billing.get_balance(session, tenant_id)
    if balance.seconds <= 0:
        raise ApiError("quota_exceeded", "subscription is not active and no prepaid credit remains")
    return replace(value, price_per_minute_toman=price_per_minute_toman)
