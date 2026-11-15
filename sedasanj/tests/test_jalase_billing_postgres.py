"""Jalase-Negar plans, token metering shown as hours, and monthly purchases (PAYMENT_TEST_DSN)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from tests.plan_helpers import requires_postgres, scratch  # noqa: F401

from app import db
from app.errors import ApiError
from app.models import (
    AiUsageEvent,
    Order,
    PlanVersion,
    Subscription,
    TokenGrant,
    TokenPackage,
)
from app.routers import token_packages
from app.services import (
    commerce,
    jalase_accounts,
    jalase_billing,
    payments,
    subscription_state,
    token_quota,
)

pytestmark = requires_postgres

TENANT_TABLES = (
    "api_keys",
    "audit_events",
    "invoices",
    "order_items",
    "orders",
    "ai_usage_events",
    "token_grants",
    "ledger_entries",
    "credit_grants",
    "tenant_balance_cache",
    "trial_claims",
    "subscriptions",
    "users",
)


def new_mobile() -> str:
    return "09" + str(uuid4().int)[:9]


@pytest.fixture()
async def created(scratch: None) -> AsyncIterator[list[UUID]]:  # noqa: F811
    tenants: list[UUID] = []
    yield tenants
    async with db.session_scope(staff=True) as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        for tenant_id in tenants:
            for table in TENANT_TABLES:
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def account(created: list[UUID]) -> UUID:
    async with db.session_scope(staff=True) as session:
        tenant, _ = await jalase_accounts.create_personal_account(
            session, mobile=new_mobile(), display_name="سارا", ip="127.0.0.1"
        )
        created.append(tenant.id)
        return tenant.id


async def order_for(tenant_id: UUID, plan_code: str, *, period: str = "monthly") -> Order:
    async with db.session_scope(staff=True) as session:
        from app.models import Tenant, User

        tenant = await session.get(Tenant, tenant_id)
        user = (await session.execute(select(User).where(User.tenant_id == tenant_id))).scalar_one()
        assert tenant is not None
        order = await commerce.create_subscription_order(
            session,
            tenant=tenant,
            plan_code=plan_code,
            period=period,
            extra_operators=0,
            customer_name="سارا",
            customer_email=user.email,
            customer_mobile=user.mobile_number or "",
            invoice_profile={},
            idempotency_key=uuid4().hex,
            product="jalase_negar",
        )
        await session.flush()
        session.expunge_all()
        return order


async def pay(order_id: UUID) -> None:
    async with db.session_scope(staff=True) as session:
        order = await session.get(Order, order_id)
        assert order is not None
        await payments.fulfill_order(session, order)


async def active_subscription(tenant_id: UUID) -> tuple[Subscription, PlanVersion]:
    async with db.session_scope(staff=True) as session:
        sub = (
            (
                await session.execute(
                    select(Subscription)
                    .where(Subscription.tenant_id == tenant_id, Subscription.status == "active")
                    .order_by(Subscription.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert sub is not None
        version = await session.get(PlanVersion, sub.plan_version_id)
        assert version is not None
        session.expunge_all()
        return sub, version


async def use_tokens(tenant_id: UUID, tokens: int) -> None:
    async with db.session_scope(staff=True) as session:
        await token_quota.lock_tenant(session, tenant_id)
        session.add(
            AiUsageEvent(
                tenant_id=tenant_id,
                feature="meeting_document",
                provider="aiservice",
                total_tokens=tokens,
                usage_source="reported",
            )
        )
        await session.flush()
        await token_quota.consume_overflow(session, tenant_id, tokens)


async def test_free_plan_has_a_token_allowance_shown_as_hours(created: list[UUID]) -> None:
    tenant_id = await account(created)
    sub, version = await active_subscription(tenant_id)
    assert sub.llm_monthly_tokens == version.llm_monthly_tokens == 120_000
    async with db.session_scope(staff=True) as session:
        shown = await jalase_billing.usage(session, tenant_id)
    assert shown["unlimited"] is False
    assert (shown["plan_hours"], shown["remaining_hours"]) == (3.0, 3.0)
    await use_tokens(tenant_id, 60_000)
    async with db.session_scope(staff=True) as session:
        shown = await jalase_billing.usage(session, tenant_id)
    assert (shown["used_hours"], shown["remaining_hours"], shown["exhausted"]) == (1.5, 1.5, False)


async def test_catalogue_lists_the_three_paid_plans_with_their_prices(
    scratch: None,  # noqa: F811
) -> None:
    async with db.session_scope(staff=True) as session:
        catalogue = await jalase_billing.plans(session)
        free = await jalase_billing.free_plan(session)
    assert [(p["code"], p["monthly_price_toman"]) for p in catalogue] == [
        ("jn_bronze", 280_000),
        ("jn_silver", 480_000),
        ("jn_gold", 680_000),
    ]
    assert all(p["buyable"] and p["monthly_hours"] for p in catalogue)
    assert free is not None and free["buyable"] is False and free["monthly_price_toman"] == 0


async def test_buying_a_plan_replaces_the_free_one_for_one_month(created: list[UUID]) -> None:
    tenant_id = await account(created)
    order = await order_for(tenant_id, "jn_bronze")
    assert order.kind == "subscription"
    net = 280_000
    assert order.amount_toman >= net
    await pay(order.id)
    sub, version = await active_subscription(tenant_id)
    assert version.monthly_price_toman == net
    assert (sub.billing_period, sub.llm_monthly_tokens) == ("monthly", 800_000)
    assert timedelta(days=27) < sub.period_end - sub.period_start < timedelta(days=32)
    async with db.session_scope(staff=True) as session:
        paid = await session.get(Order, order.id)
        assert paid is not None and paid.status == "paid"
        shown = await jalase_billing.usage(session, tenant_id)
    assert shown["plan_hours"] == 20.0


async def test_purchase_guards(created: list[UUID]) -> None:
    tenant_id = await account(created)
    with pytest.raises(ApiError):  # annual terms are SedaSanj only
        await order_for(tenant_id, "jn_bronze", period="annual")
    with pytest.raises(ApiError):  # SedaSanj plans are not sold in Jalase-Negar
        await order_for(tenant_id, "bronze")
    with pytest.raises(ApiError):  # the free plan is not for sale
        await order_for(tenant_id, "jn_free")
    await pay((await order_for(tenant_id, "jn_bronze")).id)
    with pytest.raises(ApiError) as other:  # a running paid plan changes after its month
        await order_for(tenant_id, "jn_gold")
    assert other.value.code == "subscription_exists"


async def test_renewing_the_same_plan_extends_the_month(created: list[UUID]) -> None:
    tenant_id = await account(created)
    await pay((await order_for(tenant_id, "jn_silver")).id)
    first, _ = await active_subscription(tenant_id)
    await pay((await order_for(tenant_id, "jn_silver")).id)
    second, _ = await active_subscription(tenant_id)
    assert second.period_start == first.period_start
    assert second.period_end > first.period_end + timedelta(days=27)


async def test_sedasanj_cannot_order_monthly(scratch: None) -> None:  # noqa: F811
    with pytest.raises(ApiError):
        await commerce.create_subscription_order(
            None,  # type: ignore[arg-type]
            tenant=None,  # type: ignore[arg-type]
            plan_code="bronze",
            period="monthly",
            extra_operators=0,
            customer_name="x",
            customer_email="x@example.com",
            customer_mobile="09120000000",
            invoice_profile={},
            idempotency_key="k" * 8,
        )


async def test_bought_tokens_are_used_after_the_plan_allowance(created: list[UUID]) -> None:
    tenant_id = await account(created)
    async with db.session_scope(staff=True) as session:
        package = (
            (
                await session.execute(
                    select(TokenPackage)
                    .where(TokenPackage.product == "jalase_negar")
                    .order_by(TokenPackage.tokens)
                )
            )
            .scalars()
            .first()
        )
        assert package is not None
        user_id = (
            await session.execute(
                text("SELECT id FROM users WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
        made = await token_packages.create_pack_order(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            package_id=package.id,
            idempotency_key=uuid4().hex,
            product="jalase_negar",
            ip=None,
        )
        order_id = UUID(made["id"])
        assert made["amount_toman"] >= package.price_toman
        sedasanj_pack = TokenPackage(
            name="x" * 3, tokens=1000, price_toman=1000, active=True, product="sedasanj"
        )
        session.add(sedasanj_pack)
        await session.flush()
        with pytest.raises(ApiError):  # a SedaSanj pack cannot be bought from the app
            await token_packages.create_pack_order(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                package_id=sedasanj_pack.id,
                idempotency_key=uuid4().hex,
                product="jalase_negar",
                ip=None,
            )
        await session.delete(sedasanj_pack)
    await pay(order_id)
    await use_tokens(tenant_id, 150_000)  # 120k plan allowance + 30k from the pack
    async with db.session_scope(staff=True) as session:
        grant = (
            await session.execute(select(TokenGrant).where(TokenGrant.tenant_id == tenant_id))
        ).scalar_one()
        shown = await jalase_billing.usage(session, tenant_id)
    assert grant.remaining_tokens == 120_000
    assert (shown["plan_remaining_hours"], shown["bonus_hours"]) == (0.0, 3.0)
    assert shown["exhausted"] is False


async def test_exhausted_free_plan_refuses_new_ai_work(created: list[UUID]) -> None:
    tenant_id = await account(created)
    await use_tokens(tenant_id, 120_000)
    async with db.session_scope(staff=True) as session:
        shown = await jalase_billing.usage(session, tenant_id)
        assert shown["exhausted"] is True
        with pytest.raises(ApiError) as refused:
            await token_quota.require_budget(session, tenant_id)
    assert refused.value.code == "token_quota_exceeded"


async def test_a_lapsed_paid_month_returns_to_the_free_plan(created: list[UUID]) -> None:
    tenant_id = await account(created)
    await pay((await order_for(tenant_id, "jn_gold")).id)
    later = datetime.now(UTC) + timedelta(days=60)
    async with db.session_scope(staff=True) as session:
        changed = await subscription_state.expire_due(session, tenant_id, later, 0)
        assert changed == 1
        assert await jalase_accounts.restore_free_plan(session, tenant_id, later) is True
    sub, version = await active_subscription(tenant_id)
    assert (sub.billing_period, sub.llm_monthly_tokens) == ("monthly", 120_000)
    assert sub.period_end.year == 9999 and version.monthly_price_toman == 0
    async with db.session_scope(staff=True) as session:
        assert await jalase_accounts.restore_free_plan(session, tenant_id, later) is False


async def test_admin_prices_a_jalase_plan_monthly_and_publishes_it(scratch: None) -> None:  # noqa: F811
    from types import SimpleNamespace

    from pydantic import ValidationError

    from app.models import Plan, StaffUser
    from app.routers import commerce as router

    payload = {
        "annual_price_toman": None,
        "monthly_price_toman": 150_000,
        "base_operators": 1,
        "intro_minutes": 600,
        "overage_price_per_minute_toman": 2000,
        "assistant_tier": "demo",
        "assistant_monthly_messages": 0,
        "assistant_source_limit": 1,
        "llm_monthly_tokens": 400_000,
    }
    with pytest.raises(ValidationError):  # a monthly price is required
        router.JalasePlanVersionCreate(**{**payload, "monthly_price_toman": 0})
    code = f"jn_t{uuid4().hex[:6]}"
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
    async with db.session_scope(staff=True) as session:
        staff = StaffUser(
            email=f"jn-plan-{uuid4().hex[:8]}@example.com", password_hash="x", role="super_admin"
        )
        session.add(staff)
        await session.flush()
        try:
            await router.create_plan(
                router.PlanCreate(code=code, name="آزمون", product="jalase_negar"),
                request,  # type: ignore[arg-type]
                staff,  # type: ignore[arg-type]
                session,
            )
            with pytest.raises(ApiError):  # the SedaSanj form refuses a Jalase plan
                await router.create_plan_version(
                    code,
                    router.PlanVersionCreate(
                        **{k: v for k, v in payload.items() if k != "monthly_price_toman"}
                        | {"annual_price_toman": 1}
                    ),
                    request,  # type: ignore[arg-type]
                    staff,  # type: ignore[arg-type]
                    session,
                )
            made = await router.create_jalase_plan_version(
                code,
                router.JalasePlanVersionCreate(**payload),
                request,  # type: ignore[arg-type]
                staff,  # type: ignore[arg-type]
                session,
            )
            published = await router.publish_plan_version(
                UUID(made["id"]),
                router.PlanPublish(reason="آزمون"),
                request,  # type: ignore[arg-type]
                staff,  # type: ignore[arg-type]
                session,
            )
            assert published["status"] == "published"
            listed = await router.admin_plans(
                staff, session, cursor=0, limit=200, product="jalase_negar"
            )  # type: ignore[arg-type]
            mine = next(i for i in listed["items"] if i["code"] == code)
            assert (mine["monthly_price_toman"], mine["product"]) == (150_000, "jalase_negar")
            assert all(i["product"] == "jalase_negar" for i in listed["items"])
            catalogue = await jalase_billing.plans(session)
            assert code in {p["code"] for p in catalogue}
        finally:
            await session.execute(text("SET LOCAL session_replication_role = replica"))
            await session.execute(
                text(
                    "DELETE FROM plan_versions "
                    "WHERE plan_id IN (SELECT id FROM plans WHERE code = :c)"
                ),
                {"c": code},
            )
            plan = (
                await session.execute(select(Plan).where(Plan.code == code))
            ).scalar_one_or_none()
            if plan is not None:
                await session.delete(plan)
            await session.execute(
                text("DELETE FROM audit_events WHERE actor_id = :s"), {"s": staff.id}
            )
            await session.delete(staff)
