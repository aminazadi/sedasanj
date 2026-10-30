"""Monthly plan minutes: one deterministic grant per quota window of a subscription."""

from __future__ import annotations

import math
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditGrant, LedgerEntry, TenantBalanceCache
from app.services import billing
from app.services.quotas import monthly_period_end, quota_period_start


def window(subscription_start: datetime, subscription_end: datetime, now: datetime):  # type: ignore[no-untyped-def]
    start = quota_period_start(subscription_start, now)
    return start, monthly_period_end(start, subscription_end)


def period_key(subscription_id: UUID, start: datetime) -> str:
    """The only idempotency key for a window; sign-up and ingest must both use it."""
    return f"plan-credit:{subscription_id}:{start.isoformat()}"


async def expire_lapsed_grants(
    session: AsyncSession, tenant_id: UUID, cache: TenantBalanceCache, now: datetime
) -> None:
    grants = (
        (
            await session.execute(
                select(CreditGrant)
                .where(
                    CreditGrant.tenant_id == tenant_id,
                    CreditGrant.source == "monthly_plan",
                    CreditGrant.remaining_seconds > 0,
                    CreditGrant.expires_at.is_not(None),
                    CreditGrant.expires_at <= now,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for grant in grants:
        amount = grant.remaining_seconds
        cache.seconds = max(0, cache.seconds - amount)
        grant.remaining_seconds = 0
        session.add(
            LedgerEntry(
                tenant_id=tenant_id,
                call_id=None,
                kind="expiration",
                seconds_delta=-amount,
                toman_delta=0,
                idempotency_key=f"expire:{grant.id}",
            )
        )


async def ensure_period_credit(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    subscription_id: UUID,
    subscription_start: datetime,
    subscription_end: datetime,
    minutes: int,
    now: datetime,
) -> bool:
    """Grant the plan minutes of the window containing ``now`` once; True when granted."""
    start, end = window(subscription_start, subscription_end, now)
    key = period_key(subscription_id, start)
    cache = await billing._lock_cache(session, tenant_id)
    await billing._ensure_legacy_grant(session, tenant_id, cache)
    exists = (
        await session.execute(
            select(LedgerEntry.id).where(
                LedgerEntry.tenant_id == tenant_id, LedgerEntry.idempotency_key == key
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False
    await expire_lapsed_grants(session, tenant_id, cache, now)
    seconds = minutes * 60
    if seconds > 0:
        session.add(
            CreditGrant(
                tenant_id=tenant_id,
                source="monthly_plan",
                source_id=subscription_id,
                total_seconds=seconds,
                remaining_seconds=seconds,
                expires_at=end,
            )
        )
        cache.seconds += seconds
    session.add(
        LedgerEntry(
            tenant_id=tenant_id,
            call_id=None,
            kind="subscription_credit",
            seconds_delta=seconds,
            toman_delta=0,
            idempotency_key=key,
        )
    )
    return True


async def grant_upgrade_difference(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    subscription_id: UUID,
    subscription_start: datetime,
    subscription_end: datetime,
    old_minutes: int,
    new_minutes: int,
    now: datetime,
    key: str,
) -> int:
    """Extra minutes for the rest of the current window after moving to a bigger plan."""
    if new_minutes <= old_minutes:
        return 0
    start, end = window(subscription_start, subscription_end, now)
    span = max(1.0, (end - start).total_seconds())
    remaining = max(0.0, (end - now).total_seconds())
    seconds = math.ceil((new_minutes - old_minutes) * 60 * remaining / span)
    if seconds <= 0:
        return 0
    exists = (
        await session.execute(
            select(LedgerEntry.id).where(
                LedgerEntry.tenant_id == tenant_id, LedgerEntry.idempotency_key == key
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return 0
    cache = await billing._lock_cache(session, tenant_id)
    session.add(
        CreditGrant(
            tenant_id=tenant_id,
            source="monthly_plan",
            source_id=subscription_id,
            total_seconds=seconds,
            remaining_seconds=seconds,
            expires_at=end,
        )
    )
    session.add(
        LedgerEntry(
            tenant_id=tenant_id,
            call_id=None,
            kind="subscription_credit",
            seconds_delta=seconds,
            toman_delta=0,
            idempotency_key=key,
        )
    )
    cache.seconds += seconds
    return int(seconds)


async def revoke_upgrade_difference(
    session: AsyncSession, tenant_id: UUID, *, subscription_id: UUID, key: str
) -> int:
    """Take back the unused part of an upgrade grant when its order is refunded."""
    granted = (
        await session.execute(
            select(LedgerEntry.seconds_delta).where(
                LedgerEntry.tenant_id == tenant_id, LedgerEntry.idempotency_key == key
            )
        )
    ).scalar_one_or_none()
    revoke_key = f"revoke:{key}"
    done = (
        await session.execute(
            select(LedgerEntry.id).where(
                LedgerEntry.tenant_id == tenant_id, LedgerEntry.idempotency_key == revoke_key
            )
        )
    ).scalar_one_or_none()
    if not granted or done is not None:
        return 0
    cache = await billing._lock_cache(session, tenant_id)
    grants = (
        (
            await session.execute(
                select(CreditGrant)
                .where(
                    CreditGrant.tenant_id == tenant_id,
                    CreditGrant.source == "monthly_plan",
                    CreditGrant.source_id == subscription_id,
                    CreditGrant.total_seconds == granted,
                    CreditGrant.remaining_seconds > 0,
                )
                .order_by(CreditGrant.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if not grants:
        return 0
    taken = int(grants[0].remaining_seconds)
    grants[0].remaining_seconds = 0
    cache.seconds = max(0, cache.seconds - taken)
    session.add(
        LedgerEntry(
            tenant_id=tenant_id,
            call_id=None,
            kind="adjustment",
            seconds_delta=-taken,
            toman_delta=0,
            idempotency_key=revoke_key,
        )
    )
    return taken
