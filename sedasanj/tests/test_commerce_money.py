"""Tax, invoices, order limits and refunds against a disposable PostgreSQL database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from plan_helpers import (
    drop_org,
    make_org,
    request,
    requires_postgres,
    scratch,
    version_id,
)
from sqlalchemy import select, text

pytestmark = requires_postgres
__all__ = ["scratch"]


async def set_setting(key: str, value: str | None) -> None:
    from app import db
    from app.models import PlatformSetting
    from app.services import subscription_state

    async with db.session_scope(staff=True) as session:
        row = await session.get(PlatformSetting, f"commerce.{key}")
        if value is None:
            if row is not None:
                await session.delete(row)
        elif row is None:
            session.add(PlatformSetting(key=f"commerce.{key}", value=value))
        else:
            row.value = value
    subscription_state.reset_grace_cache()


def test_tax_rounds_half_up() -> None:
    from app.services.commerce import tax_for

    assert tax_for(1_000_000, 10) == 100_000
    assert tax_for(5, 10) == 1
    assert tax_for(4, 10) == 0
    assert tax_for(1_000_000, 0) == 0


async def test_subscription_order_carries_tax_and_invoice_breakdown(scratch: None) -> None:
    from app import db
    from app.models import Invoice, Order, OrderItem, Tenant
    from app.services import commerce, payments

    org = await make_org("bronze", status="expired", start_days=-400, end_days=-35)
    await set_setting("tax_percent", "10")
    try:
        async with db.session_scope(staff=True) as session:
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
            items = (
                (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id)))
                .scalars()
                .all()
            )
            net = sum(item.total_toman for item in items if item.kind != "tax")
            tax = sum(item.total_toman for item in items if item.kind == "tax")
            assert tax == commerce.tax_for(net, 10) > 0
            assert order.amount_toman == net + tax
            await payments.fulfill_order(session, order)
            await session.flush()
            invoice = (
                await session.execute(select(Invoice).where(Invoice.order_id == order.id))
            ).scalar_one()
            assert (invoice.net_toman, invoice.tax_toman, invoice.tax_percent) == (net, tax, 10)
            assert invoice.amount_toman == order.amount_toman
            assert {line["kind"] for line in invoice.lines} == {"subscription", "tax"}
            assert (await session.get(Order, order.id)).status == "paid"  # type: ignore[union-attr]
    finally:
        await set_setting("tax_percent", None)
        await drop_org(org)


async def test_credit_balance_excludes_tax(scratch: None) -> None:
    from app import db
    from app.models import Order, TenantBalanceCache
    from app.routers.commerce import CreditOrderCreate, create_credit_order
    from app.services import payments

    org = await make_org("bronze")
    await set_setting("tax_percent", "10")
    try:
        async with db.session_scope(staff=True) as session:
            out = await create_credit_order(
                CreditOrderCreate(minutes=60),
                request(),
                org.principal,
                session,
                uuid4().hex,
            )
            order = await session.get(Order, UUID(out["id"]))
            assert order is not None
            await payments.fulfill_order(session, order)
            await session.flush()
            cache = await session.get(TenantBalanceCache, org.tenant_id)
            assert cache is not None
            assert cache.seconds == 3600
            assert cache.toman < order.amount_toman
            assert cache.toman == order.amount_toman - (order.amount_toman * 10 // 110)
    finally:
        await set_setting("tax_percent", None)
        await drop_org(org)


async def test_credit_order_respects_admin_limits(scratch: None) -> None:
    from app import db
    from app.errors import ApiError
    from app.routers.commerce import CreditOrderCreate, create_credit_order

    org = await make_org("bronze")
    await set_setting("max_order_toman", "1000000")
    try:
        async with db.session_scope(staff=True) as session:
            with pytest.raises(ApiError) as caught:
                await create_credit_order(
                    CreditOrderCreate(minutes=100_000),
                    request(),
                    org.principal,
                    session,
                    uuid4().hex,
                )
            assert caught.value.code == "order_amount_too_large"
    finally:
        await set_setting("max_order_toman", None)
        await drop_org(org)


async def test_same_idempotency_key_replays_the_order(scratch: None) -> None:
    from app import db
    from app.routers.commerce import CreditOrderCreate, create_credit_order

    org = await make_org("bronze")
    key = uuid4().hex
    try:
        async with db.session_scope(staff=True) as session:
            first = await create_credit_order(
                CreditOrderCreate(minutes=30), request(), org.principal, session, key
            )
            again = await create_credit_order(
                CreditOrderCreate(minutes=30), request(), org.principal, session, key
            )
            assert first["id"] == again["id"]
    finally:
        await drop_org(org)


async def test_refund_replay_returns_the_original_refund(scratch: None) -> None:
    from app import db
    from app.models import Order, Tenant
    from app.services import commerce, payments

    org = await make_org("bronze", status="expired", start_days=-400, end_days=-35)
    try:
        async with db.session_scope(staff=True) as session:
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
            args = {
                "order_id": order.id,
                "amount_toman": order.amount_toman,
                "method": "manual",
                "reason": "test refund",
                "idempotency_key": uuid4().hex,
                "created_by": None,
            }
            first = await payments.refund_order(session, **args)  # type: ignore[arg-type]
            again = await payments.refund_order(session, **args)  # type: ignore[arg-type]
            assert again.id == first.id
            assert (await session.get(Order, order.id)).status == "refunded"  # type: ignore[union-attr]
    finally:
        await drop_org(org)


async def test_refunding_an_upgrade_restores_the_previous_plan(scratch: None) -> None:
    from app import db
    from app.models import Order, PlanVersion, Subscription
    from app.routers.commerce import SubscriptionChangeCreate, change_subscription
    from app.services import payments

    org = await make_org("bronze", start_days=-100, end_days=265)
    try:
        async with db.session_scope(staff=True) as session:
            bronze_version = (await session.get(Subscription, org.subscription_id)).plan_version_id  # type: ignore[union-attr]
            out = await change_subscription(
                SubscriptionChangeCreate(plan_code="gold", extra_operators=0),
                request(),
                org.principal,
                session,
                uuid4().hex,
            )
            order = await session.get(Order, UUID(out["order_id"]))
            assert order is not None
            await payments.fulfill_order(session, order)
            await session.flush()
            gold = await session.get(PlanVersion, await version_id(session, "gold"))
            sub = await session.get(Subscription, org.subscription_id)
            assert gold is not None and sub is not None and sub.plan_version_id == gold.id
            await payments.refund_order(
                session,
                order_id=order.id,
                amount_toman=order.amount_toman,
                method="manual",
                reason="test refund",
                idempotency_key=uuid4().hex,
                created_by=None,  # type: ignore[arg-type]
            )
            await session.refresh(sub)
            assert sub.plan_version_id == bronze_version
            assert sub.status == "active"
    finally:
        await drop_org(org)


async def test_refunding_an_early_renewal_keeps_the_paid_term(scratch: None) -> None:
    from app import db
    from app.models import Subscription, Tenant
    from app.services import commerce, payments

    org = await make_org("bronze", start_days=-340, end_days=25)
    try:
        async with db.session_scope(staff=True) as session:
            sub = await session.get(Subscription, org.subscription_id)
            assert sub is not None
            original_end = sub.period_end
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
            await payments.refund_order(
                session,
                order_id=order.id,
                amount_toman=order.amount_toman,
                method="manual",
                reason="test refund",
                idempotency_key=uuid4().hex,
                created_by=None,  # type: ignore[arg-type]
            )
            await session.flush()
            await session.refresh(sub)
            assert sub.status == "active"
            assert sub.period_end == original_end
            assert sub.period_end > datetime.now(UTC)
    finally:
        await drop_org(org)


async def test_operator_quota_check_takes_a_tenant_lock(scratch: None) -> None:
    from app import db
    from app.services import operator_scope

    org = await make_org("bronze")
    try:
        async with db.session_scope(staff=True) as session:
            await operator_scope.assert_operator_quota(session, org.tenant_id, extra=1)
            locks = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
                    )
                )
            ).scalar_one()
            assert locks >= 1
    finally:
        await drop_org(org)
