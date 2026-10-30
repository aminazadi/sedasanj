"""Regression tests for the plan / subscription audit (WP-0 and WP-1).

They run against a disposable, fully migrated PostgreSQL database: run
`alembic upgrade head` on a scratch database, then set PAYMENT_TEST_DSN to its asyncpg URL (the
database name must contain "scratch" or "test"). Never point it at real data.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

TEST_DSN = os.environ.get("PAYMENT_TEST_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="disposable PostgreSQL DSN not supplied")


@pytest.fixture()
async def scratch(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    from app import db
    from app.config import get_settings

    assert TEST_DSN
    database = TEST_DSN.rsplit("/", 1)[-1]
    assert "scratch" in database or "test" in database, "refusing to run on a non-test database"
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.setenv("TENANT_DATABASES_ENABLED", "false")
    get_settings.cache_clear()
    await db.dispose_engine()
    assert get_settings().database_url == TEST_DSN
    yield
    await db.dispose_engine()
    get_settings.cache_clear()


def fake_request() -> Any:
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


def fake_staff() -> Any:
    return SimpleNamespace(id=None)


def version_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "annual_price_toman": 10_000_000,
        "base_operators": 2,
        "intro_minutes": 100,
        "overage_price_per_minute_toman": 2_000,
        "assistant_tier": "simple",
        "assistant_monthly_messages": 50,
        "assistant_source_limit": 8,
    }
    values.update(overrides)
    return values


async def test_admin_can_create_plan_version(scratch: None) -> None:
    """B-01: the draft insert must not violate a NOT NULL legacy monthly price column."""
    from app import db
    from app.models import Plan
    from app.routers.commerce import PlanVersionCreate, create_plan_version

    code = f"t_{uuid4().hex[:8]}"
    async with db.session_scope(staff=True) as session:
        session.add(Plan(code=code, name="plan under test", active=True, public=False))
    try:
        async with db.session_scope(staff=True) as session:
            out = await create_plan_version(
                code,
                PlanVersionCreate(**version_payload()),  # type: ignore[arg-type]
                fake_request(),
                fake_staff(),
                session,
            )
        assert out["status"] == "draft"
        assert out["version"] == 1
    finally:
        async with db.session_scope(staff=True) as session:
            await session.execute(
                text(
                    "DELETE FROM plan_versions WHERE plan_id IN "
                    "(SELECT id FROM plans WHERE code = :c)"
                ),
                {"c": code},
            )
            await session.execute(text("DELETE FROM plans WHERE code = :c"), {"c": code})


async def test_admin_subscriptions_lists_every_row(scratch: None) -> None:
    """B-02: every subscription is listed, `q` filters rows, empty tenants add nothing."""
    from app import db
    from app.models import PlanVersion, Subscription, Tenant
    from app.routers.commerce import admin_subscriptions

    now = datetime.now(UTC)
    tenant_ids = [uuid4(), uuid4(), uuid4()]
    names = [f"alpha-{uuid4().hex[:6]}", f"beta-{uuid4().hex[:6]}", f"empty-{uuid4().hex[:6]}"]
    async with db.session_scope(staff=True) as session:
        version_id = (
            await session.execute(
                text(
                    "SELECT pv.id FROM plan_versions pv JOIN plans p ON p.id = pv.plan_id "
                    "WHERE p.code = 'bronze' AND pv.status = 'published' "
                    "ORDER BY pv.version DESC LIMIT 1"
                )
            )
        ).scalar_one()
        version = await session.get(PlanVersion, version_id)
        assert version is not None
        for tenant_id, name in zip(tenant_ids, names, strict=True):
            session.add(Tenant(id=tenant_id, name=name, price_per_minute_toman=2000))
        await session.flush()
        for tenant_id, statuses in (
            (tenant_ids[0], ("active", "expired")),
            (tenant_ids[1], ("active",)),
        ):
            for index, status in enumerate(statuses):
                session.add(
                    Subscription(
                        tenant_id=tenant_id,
                        plan_version_id=version.id,
                        status=status,
                        billing_period="annual",
                        period_start=now - timedelta(days=400 + index),
                        period_end=now + timedelta(days=30)
                        if status == "active"
                        else now - timedelta(days=35),
                        base_operators=version.base_operators,
                        price_per_minute_toman=2000,
                        assistant_tier=version.assistant_tier,
                        assistant_monthly_messages=version.assistant_monthly_messages,
                        assistant_source_limit=version.assistant_source_limit,
                    )
                )
    try:
        async with db.session_scope(staff=True) as session:
            everything = await admin_subscriptions(
                fake_staff(), session, q=None, subscription_status=None, cursor=0, limit=200
            )
            mine = [i for i in everything["items"] if str(i["tenant_id"]) in map(str, tenant_ids)]
            assert len(mine) == 3
            assert {i["tenant_name"] for i in mine} == set(names[:2])
            filtered = await admin_subscriptions(
                fake_staff(), session, q=names[1], subscription_status=None, cursor=0, limit=200
            )
            assert {i["tenant_name"] for i in filtered["items"]} == {names[1]}
    finally:
        async with db.session_scope(staff=True) as session:
            for tenant_id in tenant_ids:
                await session.execute(
                    text("DELETE FROM subscriptions WHERE tenant_id = :t"), {"t": tenant_id}
                )
                await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def test_large_credit_order_fits_the_amount_column(scratch: None) -> None:
    """B-04: the maximum credit quote (1,000,000 min x 7,000) exceeds a 32-bit column."""
    from app import db
    from app.models import Order, Tenant

    tenant_id = uuid4()
    amount = 1_000_000 * 7_000
    async with db.session_scope(staff=True) as session:
        session.add(Tenant(id=tenant_id, name="big-order", price_per_minute_toman=7000))
    try:
        async with db.session_scope(staff=True) as session:
            session.add(
                Order(
                    tenant_id=tenant_id,
                    number=f"T-{uuid4().hex[:10]}",
                    kind="credit",
                    status="draft",
                    amount_toman=amount,
                    callback_token=uuid4().hex,
                    idempotency_key=uuid4().hex,
                    customer_name="t",
                    customer_email="t@example.com",
                    customer_mobile="09120000000",
                )
            )
        async with db.session_scope(staff=True) as session:
            stored = (
                await session.execute(
                    select(Order.amount_toman).where(Order.tenant_id == tenant_id)
                )
            ).scalar_one()
        assert stored == amount
    finally:
        async with db.session_scope(staff=True) as session:
            await session.execute(text("DELETE FROM orders WHERE tenant_id = :t"), {"t": tenant_id})
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def test_negative_order_amount_is_rejected(scratch: None) -> None:
    """B-40: the database refuses a negative order amount."""
    from app import db
    from app.models import Order, Tenant

    tenant_id = uuid4()
    async with db.session_scope(staff=True) as session:
        session.add(Tenant(id=tenant_id, name="neg-order", price_per_minute_toman=7000))
    try:
        with pytest.raises(DBAPIError):
            async with db.session_scope(staff=True) as session:
                session.add(
                    Order(
                        tenant_id=tenant_id,
                        number=f"T-{uuid4().hex[:10]}",
                        kind="credit",
                        status="draft",
                        amount_toman=-1,
                        callback_token=uuid4().hex,
                        idempotency_key=uuid4().hex,
                        customer_name="t",
                        customer_email="t@example.com",
                        customer_mobile="09120000000",
                    )
                )
    finally:
        async with db.session_scope(staff=True) as session:
            await session.execute(text("DELETE FROM orders WHERE tenant_id = :t"), {"t": tenant_id})
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def test_entitlement_lock_does_not_lock_shared_plan_rows(scratch: None) -> None:
    """B-05: `effective(lock=True)` must lock the subscription row only."""
    from app import db
    from app.models import PlanVersion, Subscription, Tenant
    from app.services import entitlements

    now = datetime.now(UTC)
    tenant_id = uuid4()
    async with db.session_scope(staff=True) as session:
        version_id = (
            await session.execute(
                text(
                    "SELECT pv.id FROM plan_versions pv JOIN plans p ON p.id = pv.plan_id "
                    "WHERE p.code = 'bronze' AND pv.status = 'published' "
                    "ORDER BY pv.version DESC LIMIT 1"
                )
            )
        ).scalar_one()
        version = await session.get(PlanVersion, version_id)
        assert version is not None
        session.add(Tenant(id=tenant_id, name="lock-test", price_per_minute_toman=2000))
        await session.flush()
        session.add(
            Subscription(
                tenant_id=tenant_id,
                plan_version_id=version.id,
                status="active",
                billing_period="annual",
                period_start=now - timedelta(days=10),
                period_end=now + timedelta(days=300),
                base_operators=version.base_operators,
                price_per_minute_toman=2000,
                assistant_tier=version.assistant_tier,
                assistant_monthly_messages=version.assistant_monthly_messages,
                assistant_source_limit=version.assistant_source_limit,
            )
        )
    try:
        async with db.session_scope(staff=True) as holder:
            await entitlements.effective(holder, tenant_id, lock=True)
            async with db.session_scope(staff=True) as other:
                locked = (
                    await other.execute(
                        text("SELECT id FROM plan_versions WHERE id = :v FOR UPDATE NOWAIT"),
                        {"v": version_id},
                    )
                ).scalar_one()
                assert UUID(str(locked)) == version_id
    finally:
        async with db.session_scope(staff=True) as session:
            await session.execute(
                text("DELETE FROM subscriptions WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def test_reading_entitlements_does_not_write_expiry(scratch: None) -> None:
    """B-41: a read path must not flip the subscription status."""
    from app import db
    from app.models import PlanVersion, Subscription, Tenant
    from app.services import entitlements

    now = datetime.now(UTC)
    tenant_id = uuid4()
    async with db.session_scope(staff=True) as session:
        version_id = (
            await session.execute(
                text(
                    "SELECT pv.id FROM plan_versions pv JOIN plans p ON p.id = pv.plan_id "
                    "WHERE p.code = 'bronze' AND pv.status = 'published' "
                    "ORDER BY pv.version DESC LIMIT 1"
                )
            )
        ).scalar_one()
        version = await session.get(PlanVersion, version_id)
        assert version is not None
        session.add(Tenant(id=tenant_id, name="read-test", price_per_minute_toman=2000))
        await session.flush()
        session.add(
            Subscription(
                tenant_id=tenant_id,
                plan_version_id=version.id,
                status="active",
                billing_period="annual",
                period_start=now - timedelta(days=400),
                period_end=now - timedelta(days=1),
                base_operators=version.base_operators,
                price_per_minute_toman=2000,
                assistant_tier=version.assistant_tier,
                assistant_monthly_messages=version.assistant_monthly_messages,
                assistant_source_limit=version.assistant_source_limit,
            )
        )
    try:
        async with db.session_scope(staff=True) as session:
            value = await entitlements.effective(session, tenant_id)
            assert value.consumption_allowed is False
            assert value.status == "expired"
        async with db.session_scope(staff=True) as session:
            stored = (
                await session.execute(
                    select(Subscription.status).where(Subscription.tenant_id == tenant_id)
                )
            ).scalar_one()
        assert stored == "active"
    finally:
        async with db.session_scope(staff=True) as session:
            await session.execute(
                text("DELETE FROM subscriptions WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def test_one_failing_tenant_does_not_stop_renewal_preparation(
    scratch: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-08: a pricing failure for one tenant must not abort the whole renewal run."""
    from app import db
    from app.models import Order, PlanVersion, Subscription, Tenant, User
    from app.services import commerce, maintenance

    now = datetime.now(UTC)
    tenant_ids = [uuid4(), uuid4()]
    async with db.session_scope(staff=True) as session:
        version_id = (
            await session.execute(
                text(
                    "SELECT pv.id FROM plan_versions pv JOIN plans p ON p.id = pv.plan_id "
                    "WHERE p.code = 'bronze' AND pv.status = 'published' "
                    "ORDER BY pv.version DESC LIMIT 1"
                )
            )
        ).scalar_one()
        version = await session.get(PlanVersion, version_id)
        assert version is not None
        for index, tenant_id in enumerate(tenant_ids):
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"renew-{index}-{uuid4().hex[:6]}",
                    price_per_minute_toman=2000,
                    created_at=now - timedelta(days=1000 - index),
                )
            )
        await session.flush()
        for tenant_id in tenant_ids:
            session.add(
                Subscription(
                    tenant_id=tenant_id,
                    plan_version_id=version.id,
                    status="active",
                    billing_period="annual",
                    period_start=now - timedelta(days=360),
                    period_end=now + timedelta(days=2),
                    base_operators=version.base_operators,
                    price_per_minute_toman=2000,
                    assistant_tier=version.assistant_tier,
                    assistant_monthly_messages=version.assistant_monthly_messages,
                    assistant_source_limit=version.assistant_source_limit,
                )
            )
            session.add(
                User(
                    tenant_id=tenant_id,
                    email=f"{uuid4().hex[:8]}@example.com",
                    role="org_admin",
                    password_hash="x",
                )
            )
    original = commerce.subscription_amount
    calls: list[int] = []

    def flaky(*args: Any, **kwargs: Any) -> tuple[int, int]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return original(*args, **kwargs)

    monkeypatch.setattr(commerce, "subscription_amount", flaky)
    try:
        created = await maintenance.prepare_renewal_orders()
        assert created >= 1
        async with db.session_scope(staff=True) as session:
            orders = (
                (
                    await session.execute(
                        select(Order.tenant_id).where(Order.tenant_id.in_(tenant_ids))
                    )
                )
                .scalars()
                .all()
            )
        assert len(orders) == 1, (orders, tenant_ids, created)
    finally:
        async with db.session_scope(staff=True) as session:
            for tenant_id in tenant_ids:
                for table in ("order_items", "orders", "subscriptions", "users"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                    )
                await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
