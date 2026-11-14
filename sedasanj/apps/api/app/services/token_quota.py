"""Per-plan LLM token budget, measured only from provider-reported usage.

The plan grants ``llm_monthly_tokens`` per quota window (``None`` = unlimited).  Usage is read
from ``ai_usage_events`` (exact counts reported by aiservice / 9Router, never estimated).
Tokens used beyond the plan's allowance are taken from purchased/staff ``token_grants``; the
deduction happens in the same transaction as the usage row, serialized per tenant, so the
numbers shown to the customer, the gate and the ledger always agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import AiUsageEvent, TokenGrant
from app.services import entitlements
from app.services.quotas import quota_period_start


@dataclass(frozen=True)
class TokenBudget:
    unlimited: bool
    limit: int  # plan allowance for the window (0 when unlimited)
    used: int  # tokens reported in the window
    plan_remaining: int
    topup_remaining: int
    unavailable_events: int  # calls whose provider reported no usage (not counted as zero)
    period_start: datetime | None
    period_end: datetime | None

    @property
    def remaining(self) -> int | None:
        return None if self.unlimited else self.plan_remaining + self.topup_remaining


async def lock_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Serialize token accounting per tenant for the rest of the transaction."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"llm-tokens:{tenant_id}"},
    )


async def _window_usage(session: AsyncSession, tenant_id: UUID, start: datetime) -> tuple[int, int]:
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(AiUsageEvent.total_tokens), 0),
                func.count().filter(AiUsageEvent.usage_source == "unavailable"),
            ).where(AiUsageEvent.tenant_id == tenant_id, AiUsageEvent.created_at >= start)
        )
    ).one()
    return int(row[0]), int(row[1])


async def _topup_remaining(session: AsyncSession, tenant_id: UUID, now: datetime) -> int:
    return int(
        (
            await session.execute(
                select(func.coalesce(func.sum(TokenGrant.remaining_tokens), 0)).where(
                    TokenGrant.tenant_id == tenant_id,
                    TokenGrant.remaining_tokens > 0,
                    or_(TokenGrant.expires_at.is_(None), TokenGrant.expires_at > now),
                )
            )
        ).scalar_one()
    )


async def budget(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    value: entitlements.Entitlements | None = None,
    now: datetime | None = None,
) -> TokenBudget:
    now = now or datetime.now(UTC)
    value = value or await entitlements.effective(session, tenant_id)
    topup = await _topup_remaining(session, tenant_id, now)
    if value.llm_monthly_tokens is None or value.period_start is None:
        return TokenBudget(True, 0, 0, 0, topup, 0, None, None)
    start = quota_period_start(value.period_start, now)
    used, unavailable = await _window_usage(session, tenant_id, start)
    limit = value.llm_monthly_tokens
    return TokenBudget(
        False, limit, used, max(0, limit - used), topup, unavailable, start, value.period_end
    )


async def require_budget(session: AsyncSession, tenant_id: UUID) -> TokenBudget:
    """Refuse new AI work once the plan's tokens and any top-up are used up."""
    result = await budget(session, tenant_id)
    if not result.unlimited and (result.remaining or 0) <= 0:
        raise ApiError(
            "token_quota_exceeded",
            "monthly LLM token budget is exhausted; buy tokens or upgrade the plan",
        )
    return result


async def consume_overflow(
    session: AsyncSession, tenant_id: UUID, tokens: int, *, now: datetime | None = None
) -> int:
    """Take the part of ``tokens`` that exceeds the plan allowance from top-up grants.

    Call in the transaction that inserted the usage row, after ``lock_tenant``.  Returns the
    number of top-up tokens consumed.
    """
    if tokens <= 0:
        return 0
    now = now or datetime.now(UTC)
    value = await entitlements.effective(session, tenant_id)
    if value.llm_monthly_tokens is None or value.period_start is None:
        return 0
    start = quota_period_start(value.period_start, now)
    used, _ = await _window_usage(session, tenant_id, start)  # includes this event
    limit = value.llm_monthly_tokens
    overflow = max(0, used - limit) - max(0, used - tokens - limit)
    if overflow <= 0:
        return 0
    grants = (
        (
            await session.execute(
                select(TokenGrant)
                .where(
                    TokenGrant.tenant_id == tenant_id,
                    TokenGrant.remaining_tokens > 0,
                    or_(TokenGrant.expires_at.is_(None), TokenGrant.expires_at > now),
                )
                .order_by(TokenGrant.expires_at.asc().nulls_last(), TokenGrant.created_at)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    left = overflow
    for grant in grants:
        take = min(grant.remaining_tokens, left)
        grant.remaining_tokens -= take
        left -= take
        if left == 0:
            break
    return overflow - left


async def require_ai_work(session: AsyncSession, tenant_id: UUID) -> None:
    """Gate for re-running AI on existing data: active subscription and tokens left."""
    await entitlements.require_consumption(session, tenant_id)
    await require_budget(session, tenant_id)
