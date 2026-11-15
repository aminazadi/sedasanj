"""Jalase-Negar usage shown as hours, and the plan catalogue the app sells from.

The meter itself is the existing LLM token budget (`token_quota`): provider-reported tokens are
deducted from the plan's monthly allowance first, then from bought or gift token grants.  This
module only converts tokens to the "about N hours of meetings" the app shows, using the factor
the admin sets (`jalase_tokens_per_hour`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import commerce, platform, token_quota

PRODUCT = "jalase_negar"


def to_hours(tokens: int, per_hour: int) -> float:
    """Tokens as hours with one decimal; never negative."""
    return round(max(0, tokens) / max(1, per_hour), 1)


async def usage(session: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    per_hour = await platform.jalase_tokens_per_hour(session)
    budget = await token_quota.budget(session, tenant_id)
    if budget.unlimited:
        return {"unlimited": True, "tokens_per_hour": per_hour}
    return {
        "unlimited": False,
        "tokens_per_hour": per_hour,
        "plan_hours": to_hours(budget.limit, per_hour),
        "used_hours": to_hours(min(budget.used, budget.limit), per_hour),
        "plan_remaining_hours": to_hours(budget.plan_remaining, per_hour),
        "bonus_hours": to_hours(budget.topup_remaining, per_hour),
        "remaining_hours": to_hours(budget.plan_remaining + budget.topup_remaining, per_hour),
        "exhausted": (budget.remaining or 0) <= 0,
        "resets_at": budget.period_end,
    }


async def plans(session: AsyncSession) -> list[dict[str, Any]]:
    """The public Jalase-Negar plans (free first) with their monthly allowance in hours."""
    per_hour = await platform.jalase_tokens_per_hour(session)
    out: list[dict[str, Any]] = []
    for plan, version in await commerce.public_plans(session, product=PRODUCT):
        out.append(_plan(plan.code, plan.name, version, per_hour, buyable=plan.sellable))
    return out


def _plan(code: str, name: str, version: Any, per_hour: int, *, buyable: bool) -> dict[str, Any]:
    tokens = version.llm_monthly_tokens
    return {
        "code": code,
        "name": name,
        "monthly_price_toman": version.monthly_price_toman,
        "monthly_hours": None if tokens is None else to_hours(tokens, per_hour),
        "buyable": buyable and version.monthly_price_toman > 0,
    }


async def free_plan(session: AsyncSession) -> dict[str, Any] | None:
    """The permanent free plan, which is not public but is shown as the starting point."""
    per_hour = await platform.jalase_tokens_per_hour(session)
    plan, version = await commerce.plan_version_by_code(session, "jn_free", product=PRODUCT)
    return _plan(plan.code, plan.name, version, per_hour, buyable=False)


def now() -> datetime:
    return datetime.now(UTC)
