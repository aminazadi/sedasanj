from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import ApiError
from app.models import (
    CreditGrant,
    CreditReservation,
    LedgerEntry,
    ReservationAllocation,
    Tenant,
    TenantBalanceCache,
)


@dataclass(frozen=True)
class Balance:
    seconds: int
    toman: int


def billable_seconds(duration_ms: int) -> int:
    """§10: minimum charge is 30 seconds, then per whole second."""
    return max(get_settings().min_billable_seconds, math.ceil(duration_ms / 1000))


def seconds_to_toman(seconds: int, price_per_minute_toman: int) -> int:
    return math.ceil(seconds * price_per_minute_toman / 60)


async def effective_price_per_minute(
    session: AsyncSession, tenant_id: UUID, *, include_pending: bool = False
) -> int:
    from app.models import Plan, PlanVersion, Subscription

    plan_price = (
        await session.execute(
            select(Plan.code, PlanVersion.overage_price_per_minute_toman)
            .join(PlanVersion, PlanVersion.plan_id == Plan.id)
            .join(Subscription, Subscription.plan_version_id == PlanVersion.id)
            .where(
                Subscription.tenant_id == tenant_id,
                Subscription.status.in_(
                    ("active", "trialing", "pending_payment", "expired", "canceled")
                    if include_pending
                    else ("active", "trialing", "expired", "canceled")
                ),
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if plan_price is None or plan_price[0] == "demo":
        return 7_000
    return int(plan_price[1])


async def get_balance(session: AsyncSession, tenant_id: UUID) -> Balance:
    row = (
        await session.execute(
            select(TenantBalanceCache).where(TenantBalanceCache.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return Balance(seconds=0, toman=0)
    return Balance(seconds=int(row.seconds or 0), toman=int(row.toman or 0))


def normalize_balance_cache(row: TenantBalanceCache) -> TenantBalanceCache:
    row.seconds = int(row.seconds or 0)
    row.toman = int(row.toman or 0)
    return row


async def _lock_cache(session: AsyncSession, tenant_id: UUID) -> TenantBalanceCache:
    row = (
        await session.execute(
            select(TenantBalanceCache)
            .where(TenantBalanceCache.tenant_id == tenant_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = TenantBalanceCache(tenant_id=tenant_id, seconds=0, toman=0)
        session.add(row)
        await session.flush()
        row = (
            await session.execute(
                select(TenantBalanceCache)
                .where(TenantBalanceCache.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one()
    return normalize_balance_cache(row)


async def _existing_entry(
    session: AsyncSession, tenant_id: UUID, idempotency_key: str
) -> LedgerEntry | None:
    return (
        await session.execute(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == tenant_id,
                LedgerEntry.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()


async def _ensure_legacy_grant(
    session: AsyncSession, tenant_id: UUID, cache: TenantBalanceCache
) -> None:
    grant_count = (
        await session.execute(
            select(func.count(CreditGrant.id)).where(CreditGrant.tenant_id == tenant_id)
        )
    ).scalar_one()
    if grant_count == 0 and cache.seconds > 0:
        session.add(
            CreditGrant(
                tenant_id=tenant_id,
                source="legacy",
                total_seconds=cache.seconds,
                remaining_seconds=cache.seconds,
            )
        )
        await session.flush()


async def _allocate_grants(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    reservation_id: UUID,
    seconds: int,
) -> None:
    if seconds <= 0:
        return
    grants = (
        await session.execute(
            select(CreditGrant)
            .where(
                CreditGrant.tenant_id == tenant_id,
                CreditGrant.remaining_seconds > 0,
                (CreditGrant.expires_at.is_(None))
                | (CreditGrant.expires_at > datetime.now(UTC)),
            )
            .order_by(CreditGrant.expires_at.asc().nulls_last(), CreditGrant.created_at)
            .with_for_update()
        )
    ).scalars().all()
    remaining = seconds
    for grant in grants:
        if remaining <= 0:
            break
        allocated = min(remaining, grant.remaining_seconds)
        grant.remaining_seconds -= allocated
        existing = (
            await session.execute(
                select(ReservationAllocation).where(
                    ReservationAllocation.reservation_id == reservation_id,
                    ReservationAllocation.grant_id == grant.id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                ReservationAllocation(
                    tenant_id=tenant_id,
                    reservation_id=reservation_id,
                    grant_id=grant.id,
                    seconds=allocated,
                )
            )
        else:
            existing.seconds += allocated
        remaining -= allocated
    if remaining:
        raise ApiError("insufficient_credit", "available credit grants are insufficient")


async def _restore_allocations(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    reservation_id: UUID,
    seconds: int,
) -> int:
    allocations = (
        await session.execute(
            select(ReservationAllocation)
            .where(
                ReservationAllocation.tenant_id == tenant_id,
                ReservationAllocation.reservation_id == reservation_id,
                ReservationAllocation.seconds > 0,
            )
            .order_by(ReservationAllocation.id.desc())
            .with_for_update()
        )
    ).scalars().all()
    remaining = seconds
    restored = 0
    now = datetime.now(UTC)
    for allocation in allocations:
        if remaining <= 0:
            break
        amount = min(remaining, allocation.seconds)
        grant = await session.get(CreditGrant, allocation.grant_id, with_for_update=True)
        allocation.seconds -= amount
        if grant is not None and (grant.expires_at is None or grant.expires_at > now):
            grant.remaining_seconds += amount
            restored += amount
        remaining -= amount
    return restored


async def _apply(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID | None,
    kind: str,
    seconds_delta: int,
    toman_delta: int,
    idempotency_key: str,
    reservation_id: UUID | None = None,
) -> LedgerEntry:
    """Insert a ledger entry and move the balance cache in the same transaction (§8)."""
    cache = await _lock_cache(session, tenant_id)
    entry = LedgerEntry(
        tenant_id=tenant_id,
        call_id=call_id,
        kind=kind,
        seconds_delta=seconds_delta,
        toman_delta=toman_delta,
        reservation_id=reservation_id,
        idempotency_key=idempotency_key,
    )
    session.add(entry)
    cache.seconds += seconds_delta
    cache.toman += toman_delta
    await session.flush()
    return entry


async def reserve(
    session: AsyncSession,
    *,
    tenant: Tenant,
    call_id: UUID,
    duration_ms: int,
    price_per_minute_toman: int | None = None,
) -> CreditReservation:
    """§10 reserve: lock the cache, refuse when short, then hold seconds and toman."""
    key = f"reserve:{call_id}"
    existing = await _existing_entry(session, tenant.id, key)
    if existing is not None and existing.reservation_id is not None:
        reservation = (
            await session.execute(
                select(CreditReservation).where(
                    CreditReservation.id == existing.reservation_id,
                    CreditReservation.tenant_id == tenant.id,
                )
            )
        ).scalar_one_or_none()
        if reservation is not None:
            return reservation

    cache = await _lock_cache(session, tenant.id)
    seconds = billable_seconds(duration_ms)
    price = (
        await effective_price_per_minute(session, tenant.id)
        if price_per_minute_toman is None
        else price_per_minute_toman
    )
    if cache.seconds < seconds:
        raise ApiError(
            "insufficient_credit",
            f"Reservation requires {seconds} seconds; available {cache.seconds}",
        )
    await _ensure_legacy_grant(session, tenant.id, cache)
    grants = (
        await session.execute(
            select(CreditGrant)
            .where(
                CreditGrant.tenant_id == tenant.id,
                CreditGrant.source == "monthly_plan",
                CreditGrant.remaining_seconds > 0,
                CreditGrant.expires_at > datetime.now(UTC),
            )
            .order_by(CreditGrant.expires_at.asc(), CreditGrant.created_at)
            .with_for_update()
        )
    ).scalars().all()
    free_seconds = min(seconds, sum(grant.remaining_seconds for grant in grants))
    paid_seconds = seconds - free_seconds
    toman = seconds_to_toman(paid_seconds, price)

    reservation = CreditReservation(
        tenant_id=tenant.id,
        call_id=call_id,
        seconds=seconds,
        toman=toman,
        price_per_minute_toman=price,
        free_seconds=free_seconds,
        status="held",
    )
    session.add(reservation)
    await session.flush()
    remaining_free = free_seconds
    for grant in grants:
        if remaining_free <= 0:
            break
        used = min(remaining_free, grant.remaining_seconds)
        grant.remaining_seconds -= used
        session.add(
            ReservationAllocation(
                tenant_id=tenant.id,
                reservation_id=reservation.id,
                grant_id=grant.id,
                seconds=used,
            )
        )
        remaining_free -= used
    await _allocate_grants(
        session,
        tenant_id=tenant.id,
        reservation_id=reservation.id,
        seconds=paid_seconds,
    )
    await _apply(
        session,
        tenant_id=tenant.id,
        call_id=call_id,
        kind="reservation",
        seconds_delta=-seconds,
        toman_delta=-toman,
        idempotency_key=key,
        reservation_id=reservation.id,
    )
    return reservation


async def reserve_retry(
    session: AsyncSession,
    *,
    tenant: Tenant,
    call_id: UUID,
    duration_ms: int,
    price_per_minute_toman: int | None = None,
) -> CreditReservation:
    """Create a fresh hold for a manually retried call."""
    held = (
        await session.execute(
            select(CreditReservation)
            .where(
                CreditReservation.call_id == call_id,
                CreditReservation.tenant_id == tenant.id,
                CreditReservation.status == "held",
            )
            .order_by(CreditReservation.created_at.desc(), CreditReservation.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if held is not None:
        return held

    seconds = billable_seconds(duration_ms)
    price = (
        await effective_price_per_minute(session, tenant.id)
        if price_per_minute_toman is None
        else price_per_minute_toman
    )
    toman = seconds_to_toman(seconds, price)
    cache = await _lock_cache(session, tenant.id)
    if cache.seconds < seconds:
        raise ApiError(
            "insufficient_credit",
            f"Reservation requires {seconds} seconds; available {cache.seconds}",
        )
    await _ensure_legacy_grant(session, tenant.id, cache)

    reservation = CreditReservation(
        tenant_id=tenant.id,
        call_id=call_id,
        seconds=seconds,
        toman=toman,
        price_per_minute_toman=price,
        free_seconds=0,
        status="held",
    )
    session.add(reservation)
    await session.flush()
    await _allocate_grants(
        session,
        tenant_id=tenant.id,
        reservation_id=reservation.id,
        seconds=seconds,
    )
    await _apply(
        session,
        tenant_id=tenant.id,
        call_id=call_id,
        kind="reservation",
        seconds_delta=-seconds,
        toman_delta=-toman,
        idempotency_key=f"reserve:{call_id}:{reservation.id}",
        reservation_id=reservation.id,
    )
    return reservation


async def settle(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, actual_duration_ms: int
) -> int:
    """§10 settle: charge true cost, release the leftover. Returns billed seconds."""
    reservation = (
        await session.execute(
            select(CreditReservation)
            .where(
                CreditReservation.call_id == call_id,
                CreditReservation.tenant_id == tenant_id,
                CreditReservation.status == "held",
            )
            .order_by(CreditReservation.created_at.desc(), CreditReservation.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if reservation is None:
        settled = (
            await session.execute(
                select(LedgerEntry.id)
                .where(
                    LedgerEntry.tenant_id == tenant_id,
                    LedgerEntry.call_id == call_id,
                    LedgerEntry.kind == "settlement",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if settled is not None:
            return billable_seconds(actual_duration_ms)
        raise ApiError("not_found", f"no reservation for call {call_id}")

    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise ApiError("not_found", f"tenant {tenant_id} not found")

    plan_price = int(reservation.price_per_minute_toman or 0)
    if plan_price == 0:
        plan_price = await effective_price_per_minute(session, tenant_id)
    actual_seconds = billable_seconds(actual_duration_ms)
    reserved_free = int(reservation.free_seconds or 0)
    paid_actual = max(0, actual_seconds - reserved_free)
    actual_toman = seconds_to_toman(paid_actual, plan_price)

    settled = (
        await session.execute(
            select(LedgerEntry.id)
            .where(
                LedgerEntry.tenant_id == tenant_id,
                LedgerEntry.call_id == call_id,
                LedgerEntry.kind == "settlement",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if settled is not None:
        return actual_seconds
    key = f"settle:{call_id}:{reservation.id}"

    seconds_delta = reservation.seconds - actual_seconds
    if seconds_delta > 0:
        seconds_delta = await _restore_allocations(
            session,
            tenant_id=tenant_id,
            reservation_id=reservation.id,
            seconds=seconds_delta,
        )
    elif seconds_delta < 0:
        cache = await _lock_cache(session, tenant_id)
        await _ensure_legacy_grant(session, tenant_id, cache)
        if cache.seconds < -seconds_delta:
            raise ApiError("insufficient_credit", "actual call cost exceeds available credit")
        await _allocate_grants(
            session,
            tenant_id=tenant_id,
            reservation_id=reservation.id,
            seconds=-seconds_delta,
        )

    await _apply(
        session,
        tenant_id=tenant_id,
        call_id=call_id,
        kind="settlement",
        seconds_delta=seconds_delta,
        toman_delta=reservation.toman - actual_toman,
        idempotency_key=key,
        reservation_id=reservation.id,
    )
    await session.execute(
        update(CreditReservation)
        .where(
            CreditReservation.id == reservation.id,
            CreditReservation.tenant_id == tenant_id,
        )
        .values(status="settled")
    )
    return actual_seconds


async def release(session: AsyncSession, *, tenant_id: UUID, call_id: UUID) -> None:
    """§10 release: terminal failure must not charge the tenant."""
    reservation = (
        await session.execute(
            select(CreditReservation)
            .where(
                CreditReservation.call_id == call_id,
                CreditReservation.tenant_id == tenant_id,
                CreditReservation.status == "held",
            )
            .order_by(CreditReservation.created_at.desc(), CreditReservation.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if reservation is None:
        return

    key = f"release:{call_id}:{reservation.id}"
    if await _existing_entry(session, tenant_id, key) is not None:
        return

    restored = await _restore_allocations(
        session,
        tenant_id=tenant_id,
        reservation_id=reservation.id,
        seconds=reservation.seconds,
    )
    await _apply(
        session,
        tenant_id=tenant_id,
        call_id=call_id,
        kind="release",
        seconds_delta=restored,
        toman_delta=reservation.toman,
        idempotency_key=key,
        reservation_id=reservation.id,
    )
    await session.execute(
        update(CreditReservation)
        .where(
            CreditReservation.id == reservation.id,
            CreditReservation.tenant_id == tenant_id,
        )
        .values(status="released")
    )


async def topup(
    session: AsyncSession,
    *,
    tenant: Tenant,
    minutes: int,
    idempotency_key: str,
    toman: int | None = None,
) -> LedgerEntry:
    existing = await _existing_entry(session, tenant.id, idempotency_key)
    if existing is not None:
        return existing
    seconds = minutes * 60
    amount = (
        toman
        if toman is not None
        else seconds_to_toman(
            seconds,
            await effective_price_per_minute(session, tenant.id, include_pending=True),
        )
    )
    session.add(
        CreditGrant(
            tenant_id=tenant.id,
            source="credit_purchase",
            total_seconds=seconds,
            remaining_seconds=seconds,
        )
    )
    return await _apply(
        session,
        tenant_id=tenant.id,
        call_id=None,
        kind="topup",
        seconds_delta=seconds,
        toman_delta=amount,
        idempotency_key=idempotency_key,
    )


async def adjust(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    seconds_delta: int,
    toman_delta: int,
    idempotency_key: str,
) -> LedgerEntry:
    existing = await _existing_entry(session, tenant_id, idempotency_key)
    if existing is not None:
        return existing
    if seconds_delta > 0:
        session.add(
            CreditGrant(
                tenant_id=tenant_id,
                source="admin_adjustment",
                total_seconds=seconds_delta,
                remaining_seconds=seconds_delta,
            )
        )
    return await _apply(
        session,
        tenant_id=tenant_id,
        call_id=None,
        kind="adjustment",
        seconds_delta=seconds_delta,
        toman_delta=toman_delta,
        idempotency_key=idempotency_key,
    )
