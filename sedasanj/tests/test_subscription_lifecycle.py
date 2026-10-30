"""Subscription lifecycle against a disposable PostgreSQL database (see plan_helpers)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from plan_helpers import drop_org, make_org, request, requires_postgres, scratch, version_id
from sqlalchemy import select

pytestmark = requires_postgres
__all__ = ["scratch"]


def checkout(plan: str) -> Any:
    from app.routers.commerce import CheckoutCreate

    return CheckoutCreate(
        plan_code=plan,
        billing_period="annual",
        extra_operators=0,
        customer_name="Admin",
        customer_email="admin@example.com",
        customer_mobile="09120000000",
        invoice_profile={},
        terms_accepted=True,
    )


async def test_buying_another_plan_on_a_running_plan_is_rejected(scratch: None) -> None:
    from app import db
    from app.errors import ApiError
    from app.models import Tenant
    from app.services import commerce

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            tenant = await session.get(Tenant, org.tenant_id)
            assert tenant is not None
            with pytest.raises(ApiError) as caught:
                await commerce.create_subscription_order(
                    session,
                    tenant=tenant,
                    plan_code="gold",
                    period="annual",
                    extra_operators=0,
                    customer_name="Admin",
                    customer_email="admin@example.com",
                    customer_mobile="09120000000",
                    invoice_profile={},
                    idempotency_key=uuid4().hex,
                )
            assert caught.value.code == "subscription_exists"
            same = await commerce.create_subscription_order(
                session,
                tenant=tenant,
                plan_code="bronze",
                period="annual",
                extra_operators=0,
                customer_name="Admin",
                customer_email="admin@example.com",
                customer_mobile="09120000000",
                invoice_profile={},
                idempotency_key=uuid4().hex,
            )
            assert same.amount_toman > 0
    finally:
        await drop_org(org)


async def test_early_renewal_keeps_the_anniversary_and_extends_the_term(scratch: None) -> None:
    from app import db
    from app.models import Order, Subscription, Tenant
    from app.services import commerce, payments

    org = await make_org("bronze", start_days=-340, end_days=25)
    try:
        async with db.session_scope(staff=True) as session:
            before = await session.get(Subscription, org.subscription_id)
            assert before is not None
            start, end = before.period_start, before.period_end
            tenant = await session.get(Tenant, org.tenant_id)
            assert tenant is not None
            order = await commerce.create_subscription_order(
                session,
                tenant=tenant,
                plan_code="bronze",
                period="annual",
                extra_operators=0,
                customer_name="Admin",
                customer_email="admin@example.com",
                customer_mobile="09120000000",
                invoice_profile={},
                idempotency_key=uuid4().hex,
            )
            await session.flush()
            await payments.fulfill_order(session, order)
            await session.flush()
            after = await session.get(Subscription, org.subscription_id)
            assert after is not None
            assert after.period_start == start
            assert after.period_end == commerce.add_months(end, 12)
            assert (await session.get(Order, order.id)).status == "paid"  # type: ignore[union-attr]
    finally:
        await drop_org(org)


async def test_change_downgrade_is_idempotent_and_cancelable(scratch: None) -> None:
    from app import db
    from app.errors import ApiError
    from app.models import Subscription, SubscriptionChange
    from app.routers.commerce import (
        SubscriptionChangeCreate,
        cancel_subscription_change,
        change_subscription,
    )

    org = await make_org("gold")
    key = uuid4().hex
    try:
        async with db.session_scope(staff=True) as session:
            payload = SubscriptionChangeCreate(plan_code="bronze", extra_operators=0)
            first = await change_subscription(payload, request(), org.principal, session, key)
            assert first["status"] == "scheduled"
            again = await change_subscription(payload, request(), org.principal, session, key)
            assert again["change_id"] == first["change_id"]
            with pytest.raises(ApiError) as caught:
                await change_subscription(
                    SubscriptionChangeCreate(plan_code="silver", extra_operators=0),
                    request(),
                    org.principal,
                    session,
                    key,
                )
            assert caught.value.code == "conflict_idempotency"
            rows = (
                (
                    await session.execute(
                        select(SubscriptionChange).where(
                            SubscriptionChange.tenant_id == org.tenant_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            second = await change_subscription(
                SubscriptionChangeCreate(plan_code="silver", extra_operators=0),
                request(),
                org.principal,
                session,
                uuid4().hex,
            )
            await session.flush()
            statuses = {
                str(row.id): row.status
                for row in (
                    await session.execute(
                        select(SubscriptionChange).where(
                            SubscriptionChange.tenant_id == org.tenant_id
                        )
                    )
                ).scalars()
            }
            assert statuses[first["change_id"]] == "canceled"
            assert statuses[second["change_id"]] == "scheduled"
            await cancel_subscription_change(
                UUID(second["change_id"]), request(), org.principal, session
            )
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None and sub.next_plan_version_id is None
    finally:
        await drop_org(org)


async def test_upgrade_creates_a_prorated_order_and_payment_applies_it(scratch: None) -> None:
    from app import db
    from app.models import Order, PlanVersion, Subscription, SubscriptionChange
    from app.routers.commerce import SubscriptionChangeCreate, change_subscription
    from app.services import payments

    org = await make_org("bronze", start_days=-100, end_days=265)
    try:
        async with db.session_scope(staff=True) as session:
            out = await change_subscription(
                SubscriptionChangeCreate(plan_code="gold", extra_operators=0),
                request(),
                org.principal,
                session,
                uuid4().hex,
            )
            assert out["status"] == "payment_required"
            assert out["amount_toman"] > 0
            order = await session.get(Order, UUID(out["order_id"]))
            assert order is not None
            await payments.fulfill_order(session, order)
            await session.flush()
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            gold = await session.get(PlanVersion, await version_id(session, "gold"))
            assert gold is not None and sub.plan_version_id == gold.id
            change = await session.get(SubscriptionChange, UUID(out["change_id"]))
            assert change is not None and change.status == "applied"
            assert change.previous_plan_version_id is not None
    finally:
        await drop_org(org)


async def test_paid_upgrade_for_a_lapsed_subscription_fails_the_change(scratch: None) -> None:
    from app import db
    from app.models import Order, Subscription, SubscriptionChange
    from app.routers.commerce import SubscriptionChangeCreate, change_subscription
    from app.services import payments

    org = await make_org("bronze", start_days=-100, end_days=265)
    try:
        async with db.session_scope(staff=True) as session:
            out = await change_subscription(
                SubscriptionChangeCreate(plan_code="gold", extra_operators=0),
                request(),
                org.principal,
                session,
                uuid4().hex,
            )
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            sub.period_end = datetime.now(UTC) - timedelta(days=30)
            order = await session.get(Order, UUID(out["order_id"]))
            assert order is not None
            await payments.fulfill_order(session, order)
            await session.flush()
            change = await session.get(SubscriptionChange, UUID(out["change_id"]))
            assert change is not None and change.status == "failed"
            await session.refresh(sub)
            assert sub.plan_version_id != await version_id(session, "gold")
    finally:
        await drop_org(org)


async def test_grace_keeps_service_then_expiry_flips_the_row(scratch: None) -> None:
    from app import db
    from app.models import Subscription
    from app.services import entitlements, subscription_state

    org = await make_org("bronze", start_days=-366, end_days=-1)
    try:
        async with db.session_scope(staff=True) as session:
            value = await entitlements.effective(session, org.tenant_id)
            assert value.status == "grace"
            assert value.consumption_allowed is True
            now = datetime.now(UTC)
            assert await subscription_state.expire_due(session, org.tenant_id, now, 3) == 0
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            sub.period_end = now - timedelta(days=4)
            await session.flush()
            assert await subscription_state.expire_due(session, org.tenant_id, now, 3) == 1
            await session.refresh(sub)
            assert sub.status == "expired"
            value = await entitlements.effective(session, org.tenant_id)
            assert value.consumption_allowed is False
    finally:
        await drop_org(org)


async def test_unpaid_signup_expires_and_never_shadows_a_paid_plan(scratch: None) -> None:
    from app import db
    from app.models import PlanVersion, Subscription
    from app.services import entitlements, subscription_state

    org = await make_org("bronze")
    now = datetime.now(UTC)
    try:
        async with db.session_scope(staff=True) as session:
            version = await session.get(PlanVersion, await version_id(session, "gold"))
            assert version is not None
            session.add(
                Subscription(
                    tenant_id=org.tenant_id,
                    plan_version_id=version.id,
                    status="pending_payment",
                    billing_period="annual",
                    period_start=now,
                    period_end=now + timedelta(days=7),
                    base_operators=version.base_operators,
                    price_per_minute_toman=2000,
                    assistant_tier=version.assistant_tier,
                    assistant_monthly_messages=version.assistant_monthly_messages,
                    assistant_source_limit=version.assistant_source_limit,
                )
            )
        async with db.session_scope(staff=True) as session:
            value = await entitlements.effective(session, org.tenant_id)
            assert value.status == "active"
            pending = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.tenant_id == org.tenant_id,
                        Subscription.status == "pending_payment",
                    )
                )
            ).scalar_one()
            pending.period_end = now - timedelta(days=1)
            await session.flush()
            assert await subscription_state.expire_due(session, org.tenant_id, now, 3) == 1
    finally:
        await drop_org(org)


async def test_prorating_uses_the_current_paid_year(scratch: None) -> None:
    from app.services import commerce

    now = datetime.now(UTC)
    start = now - timedelta(days=100)
    one_year = commerce.add_months(start, 12)
    stacked_end = commerce.add_months(start, 24)
    single = commerce.prorated_amount(1_000_000, start, one_year, now)
    stacked = commerce.prorated_amount(1_000_000, start, stacked_end, now)
    assert single == stacked
    assert 0 < single < 1_000_000
