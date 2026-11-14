"""Usage threshold SMS: 80% and 95% of the plan, then exhausted, for minutes and LLM tokens.

Each alert is keyed by the quota window (``window_start``), so it fires once per window per level
and a renewal or new window starts a fresh set.  Thresholds are percentages of the plan, not
fixed amounts.  Driven by the notify worker; never raises per tenant.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import routable_tenant_ids, session_scope
from app.models import CreditGrant, Tenant, TenantBalanceCache
from app.services import sms_notify, token_quota

logger = logging.getLogger(__name__)

LEVELS = ((95, "95"), (80, "80"))


def level_for(used: int, limit: int) -> str | None:
    """'exhausted', '95', '80' or None for ``used`` out of ``limit`` (limit <= 0 never alerts)."""
    if limit <= 0:
        return None
    if used >= limit:
        return "exhausted"
    percent = used * 100 // limit
    for threshold, name in LEVELS:
        if percent >= threshold:
            return name
    return None


async def _minutes_state(
    session: AsyncSession, tenant_id: UUID, now: datetime
) -> tuple[int, int, str] | None:
    """(used, plan seconds, window key) over live monthly-plan grants; None without one."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(CreditGrant.total_seconds), 0),
                func.coalesce(func.sum(CreditGrant.remaining_seconds), 0),
                func.max(CreditGrant.expires_at),
            ).where(
                CreditGrant.tenant_id == tenant_id,
                CreditGrant.source == "monthly_plan",
                CreditGrant.expires_at > now,
            )
        )
    ).one()
    total, remaining = int(row[0]), int(row[1])
    if total <= 0 or row[2] is None:
        return None
    return total - remaining, total, f"{row[2]:%Y%m%d}"


async def check_tenant(tenant_id: UUID, now: datetime | None = None) -> int:
    """Queue the SMS for the highest crossed level of minutes and tokens; return rows created."""
    now = now or datetime.now(UTC)
    created = 0
    async with session_scope(tenant_id) as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            return 0
        name = tenant.name
        minutes = await _minutes_state(session, tenant_id, now)
        balance = (
            await session.execute(
                select(TenantBalanceCache.seconds).where(TenantBalanceCache.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        tokens = await token_quota.budget(session, tenant_id, now=now)
    alerts: list[tuple[str, str, int, int, str]] = []  # kind, level, used, limit, window key
    if minutes is not None:
        used, limit, minutes_window = minutes
        level = level_for(used, limit)
        if level is not None and level != "exhausted" and (balance or 0) <= 0:
            level = "exhausted"
        if level is not None:
            alerts.append(("minutes", level, used, limit, minutes_window))
    if not tokens.unlimited and tokens.period_start is not None:
        level = level_for(tokens.used, tokens.limit)
        if level == "exhausted" and tokens.topup_remaining > 0:
            level = "95"  # top-up still covers the work: not exhausted yet
        if level is not None:
            token_window = f"{tokens.period_start:%Y%m%d}"
            alerts.append(("tokens", level, tokens.used, tokens.limit, token_window))
    for kind, level, used, limit, window_key in alerts:
        event = f"{kind}_{'exhausted' if level == 'exhausted' else level}"
        params = {
            "ORG": name,
            "PERCENT": min(100, used * 100 // limit),
            "REMAINING": max(0, limit - used) // (60 if kind == "minutes" else 1),
        }
        created += await sms_notify.enqueue_for_org_admins(
            tenant_id, event, params, f"{event}:{tenant_id}:{window_key}"
        )
    return created


async def sweep(now: datetime | None = None) -> int:
    total = 0
    for tenant_id in await routable_tenant_ids():
        try:
            total += await check_tenant(tenant_id, now)
        except Exception:  # noqa: BLE001 - one tenant must not block the sweep
            logger.exception(
                "usage alert check failed", extra={"extra_fields": {"tenant_id": str(tenant_id)}}
            )
    return total
