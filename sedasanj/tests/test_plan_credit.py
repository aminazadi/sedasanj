"""Plan minutes: one grant per quota window, shared by sign-up and ingest (WP-4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from plan_helpers import drop_org, make_org, requires_postgres, scratch
from sqlalchemy import func, select

pytestmark = requires_postgres
__all__ = ["scratch"]


async def _grants(session, tenant_id):  # type: ignore[no-untyped-def]
    from app.models import CreditGrant

    return int(
        (
            await session.execute(
                select(func.count(CreditGrant.id)).where(CreditGrant.tenant_id == tenant_id)
            )
        ).scalar_one()
    )


async def test_period_credit_is_granted_once_per_window(scratch: None) -> None:
    from app import db
    from app.models import Subscription, TenantBalanceCache
    from app.services import plan_credit

    org = await make_org("bronze")
    try:
        now = datetime.now(UTC)
        async with db.session_scope(staff=True) as session:
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            args = {
                "subscription_id": sub.id,
                "subscription_start": sub.period_start,
                "subscription_end": sub.period_end,
                "minutes": 100,
                "now": now,
            }
            first = await plan_credit.ensure_period_credit(session, org.tenant_id, **args)
            second = await plan_credit.ensure_period_credit(session, org.tenant_id, **args)
            assert (first, second) == (True, False)
            assert await _grants(session, org.tenant_id) == 1
            cache = await session.get(TenantBalanceCache, org.tenant_id)
            assert cache is not None and cache.seconds == 6000
    finally:
        await drop_org(org)


async def test_next_window_grants_again_and_expires_the_old_one(scratch: None) -> None:
    from app import db
    from app.models import Subscription, TenantBalanceCache
    from app.services import plan_credit

    org = await make_org("bronze", start_days=-40)
    try:
        async with db.session_scope(staff=True) as session:
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            base = {
                "subscription_id": sub.id,
                "subscription_start": sub.period_start,
                "subscription_end": sub.period_end,
                "minutes": 10,
            }
            early = sub.period_start + timedelta(days=1)
            late = datetime.now(UTC)
            assert await plan_credit.ensure_period_credit(session, org.tenant_id, now=early, **base)
            assert await plan_credit.ensure_period_credit(session, org.tenant_id, now=late, **base)
            cache = await session.get(TenantBalanceCache, org.tenant_id)
            assert cache is not None and cache.seconds == 600
    finally:
        await drop_org(org)


async def test_upgrade_difference_is_prorated_and_idempotent(scratch: None) -> None:
    from app import db
    from app.models import Subscription
    from app.services import plan_credit

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            args = {
                "subscription_id": sub.id,
                "subscription_start": sub.period_start,
                "subscription_end": sub.period_end,
                "old_minutes": 100,
                "new_minutes": 300,
                "now": datetime.now(UTC),
                "key": "upgrade-credit:test",
            }
            seconds = await plan_credit.grant_upgrade_difference(session, org.tenant_id, **args)
            assert 0 < seconds <= 200 * 60
            assert await plan_credit.grant_upgrade_difference(session, org.tenant_id, **args) == 0
            args["new_minutes"] = 50
            args["key"] = "upgrade-credit:down"
            assert await plan_credit.grant_upgrade_difference(session, org.tenant_id, **args) == 0
    finally:
        await drop_org(org)


async def test_assistant_window_follows_subscription_anniversary() -> None:
    from app.services import assistant_quota, quotas

    start = datetime(2026, 1, 17, tzinfo=UTC)
    now = datetime(2026, 4, 20, tzinfo=UTC)
    assert assistant_quota.period_start(start, now) == quotas.quota_period_start(start, now)
    assert assistant_quota.period_start(start, now) != quotas.calendar_month_start(now)


def test_tool_sources_respect_the_plan_limit() -> None:
    import inspect

    from app.routers import assistant

    assert "limit" in inspect.signature(assistant._tool_sources).parameters


@pytest.mark.parametrize("trial_days", [None, 0])
async def test_demo_signup_without_trial_days_is_a_config_error(
    scratch: None, trial_days: int | None
) -> None:
    from app import db
    from app.errors import ApiError
    from app.models import PlanVersion
    from app.services import signup
    from plan_helpers import version_id

    async with db.session_scope(staff=True) as session:
        vid = await version_id(session, "demo")
        version = await session.get(PlanVersion, vid)
        assert version is not None
        original = version.trial_days
        version.trial_days = trial_days
        await session.flush()
        with pytest.raises(ApiError) as caught:
            await signup.create_account(
                session,
                organization_name="Org",
                manager_name="M",
                email=f"{datetime.now(UTC).timestamp()}@example.com",
                mobile="09129999999",
                password="Str0ng-pass-123",
                plan_code="demo",
                ip="127.0.0.1",
            )
        assert caught.value.code == "plan_not_sellable"
        version.trial_days = original
        await session.rollback()


async def _call(session, tenant_id, seconds):  # type: ignore[no-untyped-def]
    from uuid import uuid4

    from app.models import Call

    now = datetime.now(UTC)
    call = Call(
        tenant_id=tenant_id,
        asterisk_uniqueid=uuid4().hex,
        started_at=now,
        ended_at=now,
        duration_ms=seconds * 1000,
        status="received",
    )
    session.add(call)
    await session.flush()
    return call


async def test_retry_hold_uses_plan_minutes_before_charging(scratch: None) -> None:
    from app import db
    from app.models import Subscription, Tenant
    from app.services import billing, plan_credit

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            sub = await session.get(Subscription, org.subscription_id)
            tenant = await session.get(Tenant, org.tenant_id)
            assert sub is not None and tenant is not None
            await plan_credit.ensure_period_credit(
                session,
                org.tenant_id,
                subscription_id=sub.id,
                subscription_start=sub.period_start,
                subscription_end=sub.period_end,
                minutes=10,
                now=datetime.now(UTC),
            )
            call = await _call(session, org.tenant_id, 120)
            hold = await billing.reserve_retry(
                session, tenant=tenant, call_id=call.id, duration_ms=120_000
            )
            assert hold.free_seconds == 120
            assert hold.toman == 0
    finally:
        await drop_org(org)


async def test_expired_plan_minutes_do_not_count_toward_a_hold(scratch: None) -> None:
    from app import db
    from app.errors import ApiError
    from app.models import CreditGrant, Tenant, TenantBalanceCache
    from app.services import billing

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            tenant = await session.get(Tenant, org.tenant_id)
            assert tenant is not None
            session.add(
                CreditGrant(
                    tenant_id=org.tenant_id,
                    source="monthly_plan",
                    source_id=org.subscription_id,
                    total_seconds=600,
                    remaining_seconds=600,
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
            session.add(TenantBalanceCache(tenant_id=org.tenant_id, seconds=600, toman=0))
            await session.flush()
            call = await _call(session, org.tenant_id, 60)
            with pytest.raises(ApiError) as caught:
                await billing.reserve(session, tenant=tenant, call_id=call.id, duration_ms=60_000)
            assert caught.value.code == "insufficient_credit"
    finally:
        await drop_org(org)


async def test_refunded_upgrade_credit_is_taken_back(scratch: None) -> None:
    from app import db
    from app.models import Subscription, TenantBalanceCache
    from app.services import plan_credit

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            granted = await plan_credit.grant_upgrade_difference(
                session,
                org.tenant_id,
                subscription_id=sub.id,
                subscription_start=sub.period_start,
                subscription_end=sub.period_end,
                old_minutes=100,
                new_minutes=300,
                now=datetime.now(UTC),
                key="upgrade-credit:o1",
            )
            taken = await plan_credit.revoke_upgrade_difference(
                session, org.tenant_id, subscription_id=sub.id, key="upgrade-credit:o1"
            )
            again = await plan_credit.revoke_upgrade_difference(
                session, org.tenant_id, subscription_id=sub.id, key="upgrade-credit:o1"
            )
            cache = await session.get(TenantBalanceCache, org.tenant_id)
            assert (taken, again) == (granted, 0)
            assert cache is not None and cache.seconds == 0
    finally:
        await drop_org(org)
