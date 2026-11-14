"""Staff and customer subscription actions (cancel, resume, stop, extend)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from plan_helpers import drop_org, make_org, request, requires_postgres, scratch
from sqlalchemy import select

pytestmark = requires_postgres
__all__ = ["scratch"]


def staff() -> Any:
    return SimpleNamespace(id=None)


async def _act(subscription_id: Any, action: str, days: int | None = None) -> dict[str, Any]:
    from app.routers.commerce import SubscriptionAdminAction, admin_subscription_action

    return await admin_subscription_action(
        subscription_id,
        SubscriptionAdminAction(action=action, reason="test", days=days),  # type: ignore[arg-type]
        request(),
        staff(),
        None,  # type: ignore[arg-type]
    )


async def test_stop_now_ends_the_term_and_closes_scheduled_changes(scratch: None) -> None:
    from app import db
    from app.models import Subscription, SubscriptionChange

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            session.add(
                SubscriptionChange(
                    tenant_id=org.tenant_id,
                    subscription_id=sub.id,
                    kind="downgrade",
                    status="scheduled",
                    target_plan_version_id=sub.plan_version_id,
                    requested_extra_operators=0,
                    effective_at=sub.period_end,
                )
            )
        out = await _act(org.subscription_id, "stop_now")
        assert out["status"] == "canceled"
        async with db.session_scope(staff=True) as session:
            change = (
                await session.execute(
                    select(SubscriptionChange).where(
                        SubscriptionChange.subscription_id == org.subscription_id
                    )
                )
            ).scalar_one()
            assert change.status == "canceled"
    finally:
        await drop_org(org)


async def test_extend_adds_days_to_a_lapsed_subscription_from_today(scratch: None) -> None:
    org = await make_org("bronze", status="expired", end_days=-20)
    try:
        out = await _act(org.subscription_id, "extend", days=30)
        assert out["status"] == "active"
        remaining = out["period_end"] - datetime.now(UTC)
        assert timedelta(days=29) < remaining <= timedelta(days=30)
    finally:
        await drop_org(org)


async def test_extend_trial_only_applies_to_trials(scratch: None) -> None:
    from app.errors import ApiError

    paid = await make_org("bronze")
    trial = await make_org("demo", status="trialing", period="trial", end_days=3)
    try:
        with pytest.raises(ApiError):
            await _act(paid.subscription_id, "extend_trial", days=5)
        out = await _act(trial.subscription_id, "extend_trial", days=5)
        assert out["period_end"] - datetime.now(UTC) > timedelta(days=7)
    finally:
        await drop_org(paid)
        await drop_org(trial)


async def test_customer_can_cancel_at_period_end_and_resume(scratch: None) -> None:
    from app import db
    from app.routers.commerce import cancel_subscription, resume_subscription

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            canceled = await cancel_subscription(request(), org.principal, session)
            assert canceled == {"cancel_at_period_end": True}
            resumed = await resume_subscription(request(), org.principal, session)
            assert resumed == {"cancel_at_period_end": False}
    finally:
        await drop_org(org)


async def test_stop_now_removes_unused_plan_minutes_but_keeps_prepaid(scratch: None) -> None:
    from app import db
    from app.models import CreditGrant, Subscription, TenantBalanceCache
    from app.services import plan_credit

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            await plan_credit.ensure_period_credit(
                session,
                org.tenant_id,
                subscription_id=sub.id,
                subscription_start=sub.period_start,
                subscription_end=sub.period_end,
                minutes=10,
                now=datetime.now(UTC),
            )
            session.add(
                CreditGrant(
                    tenant_id=org.tenant_id,
                    source="prepaid",
                    source_id=None,
                    total_seconds=300,
                    remaining_seconds=300,
                    expires_at=None,
                )
            )
            cache = await session.get(TenantBalanceCache, org.tenant_id)
            assert cache is not None
            cache.seconds += 300
        await _act(org.subscription_id, "stop_now")
        async with db.session_scope(staff=True) as session:
            cache = await session.get(TenantBalanceCache, org.tenant_id)
            assert cache is not None and cache.seconds == 300
    finally:
        await drop_org(org)
