"""Single owner of subscription status transitions.

Statuses stored in ``subscriptions.status``: ``pending_payment``, ``trialing``, ``active``,
``expired`` and ``canceled``.  ``grace`` is derived, never stored: a paid (``active``)
subscription whose period has ended keeps working for ``commerce.grace_days`` while its
renewal order stays payable.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Subscription, SubscriptionChange
from app.services import audit
from app.services.commerce_settings import get_commerce_settings

LIVE_STATUSES = ("active", "trialing")
OPEN_CHANGE_STATUSES = ("scheduled", "pending_payment")
_GRACE_TTL_SECONDS = 30.0
_grace_cache: tuple[float, int] | None = None


async def grace_days(session: AsyncSession) -> int:
    """Grace length from platform settings, cached briefly because it is read per request."""
    global _grace_cache
    now = time.monotonic()
    if _grace_cache is not None and now - _grace_cache[0] < _GRACE_TTL_SECONDS:
        return _grace_cache[1]
    value = (await get_commerce_settings(session)).grace_days
    _grace_cache = (now, value)
    return value


def reset_grace_cache() -> None:
    global _grace_cache
    _grace_cache = None


def grace_end(subscription: Subscription, days: int) -> datetime:
    """Paid subscriptions get a grace window; trials and unpaid sign-ups never do."""
    if subscription.status == "active" and subscription.billing_period != "trial":
        return subscription.period_end + timedelta(days=days)
    return subscription.period_end


def effective_status(subscription: Subscription, now: datetime, days: int) -> str:
    """Status shown to callers: adds the derived ``grace`` and reports lapsed periods."""
    if subscription.status not in {"active", "trialing", "pending_payment"}:
        return subscription.status
    if subscription.period_end > now:
        return subscription.status
    if subscription.status == "active" and grace_end(subscription, days) > now:
        return "grace"
    return "expired"


def is_consuming(subscription: Subscription, now: datetime, days: int) -> bool:
    return effective_status(subscription, now, days) in {"active", "trialing", "grace"}


async def close_open_changes(
    session: AsyncSession,
    subscription_id: UUID,
    *,
    status: str,
    kinds: tuple[str, ...] | None = None,
) -> int:
    """Move every open change of a subscription to ``status`` (canceled or failed)."""
    stmt = select(SubscriptionChange).where(
        SubscriptionChange.subscription_id == subscription_id,
        SubscriptionChange.status.in_(OPEN_CHANGE_STATUSES),
    )
    if kinds:
        stmt = stmt.where(SubscriptionChange.kind.in_(kinds))
    rows = (await session.execute(stmt.with_for_update())).scalars().all()
    for row in rows:
        row.status = status
    return len(rows)


async def expire_due(session: AsyncSession, tenant_id: UUID, now: datetime, days: int) -> int:
    """Flip every lapsed subscription of the tenant; returns how many changed."""
    rows = (
        (
            await session.execute(
                select(Subscription)
                .where(
                    Subscription.tenant_id == tenant_id,
                    Subscription.status.in_((*LIVE_STATUSES, "pending_payment")),
                    Subscription.period_end <= now,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    changed = 0
    for row in rows:
        if grace_end(row, days) > now:
            continue
        previous = row.status
        row.status = "canceled" if row.cancel_at_period_end and previous == "active" else "expired"
        row.next_plan_version_id = None
        row.updated_at = now
        await close_open_changes(session, row.id, status="canceled")
        await audit.record(
            session,
            actor_type="system",
            tenant_id=tenant_id,
            action="subscription.expired",
            payload={"subscription_id": str(row.id), "from": previous, "to": row.status},
        )
        changed += 1
    return changed


def utcnow() -> datetime:
    return datetime.now(UTC)
