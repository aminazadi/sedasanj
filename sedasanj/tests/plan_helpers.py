"""Shared fixtures for tests that need a disposable PostgreSQL database.

Set PAYMENT_TEST_DSN to the asyncpg URL of a fully migrated scratch database (its name must
contain "scratch" or "test").  Never point it at real data.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

TEST_DSN = os.environ.get("PAYMENT_TEST_DSN")
requires_postgres = pytest.mark.skipif(
    not TEST_DSN, reason="disposable PostgreSQL DSN not supplied"
)

CLEANUP_TABLES = (
    "subscription_changes",
    "refunds",
    "payment_attempts",
    "invoices",
    "order_items",
    "orders",
    "subscription_extras",
    "ledger_entries",
    "reservation_allocations",
    "credit_reservations",
    "calls",
    "credit_grants",
    "tenant_balance_cache",
    "subscriptions",
    "users",
)


@pytest.fixture()
async def scratch(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    from app import db
    from app.config import get_settings
    from app.services import subscription_state

    assert TEST_DSN
    database = TEST_DSN.rsplit("/", 1)[-1]
    assert "scratch" in database or "test" in database, "refusing to run on a non-test database"
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.setenv("TENANT_DATABASES_ENABLED", "false")
    get_settings.cache_clear()
    subscription_state.reset_grace_cache()
    await db.dispose_engine()
    yield
    await db.dispose_engine()
    get_settings.cache_clear()


def request() -> Any:
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


async def version_id(session: Any, code: str) -> UUID:
    return (
        await session.execute(
            text(
                "SELECT pv.id FROM plan_versions pv JOIN plans p ON p.id = pv.plan_id "
                "WHERE p.code = :c AND pv.status = 'published' ORDER BY pv.version DESC LIMIT 1"
            ),
            {"c": code},
        )
    ).scalar_one()


class Org:
    def __init__(self, tenant_id: UUID, user_id: UUID, subscription_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.subscription_id = subscription_id

    @property
    def principal(self) -> Any:
        return SimpleNamespace(id=self.user_id, tenant_id=self.tenant_id)


async def make_org(
    plan: str = "bronze",
    *,
    status: str = "active",
    period: str = "annual",
    start_days: int = -10,
    end_days: int = 300,
    extra_operators: int = 0,
) -> Org:
    from app import db
    from app.models import PlanVersion, Subscription, Tenant, User

    now = datetime.now(UTC)
    tenant_id = uuid4()
    async with db.session_scope(staff=True) as session:
        version = await session.get(PlanVersion, await version_id(session, plan))
        assert version is not None
        session.add(
            Tenant(id=tenant_id, name=f"life-{uuid4().hex[:6]}", price_per_minute_toman=2000)
        )
        await session.flush()
        user = User(
            tenant_id=tenant_id,
            email=f"{uuid4().hex[:8]}@example.com",
            role="org_admin",
            password_hash="x",
            display_name="Admin",
            mobile_number="09120000000",
        )
        session.add(user)
        sub = Subscription(
            tenant_id=tenant_id,
            plan_version_id=version.id,
            status=status,
            billing_period=period,
            period_start=now + timedelta(days=start_days),
            period_end=now + timedelta(days=end_days),
            base_operators=version.base_operators,
            extra_operators=extra_operators,
            price_per_minute_toman=2000,
            assistant_tier=version.assistant_tier,
            assistant_monthly_messages=version.assistant_monthly_messages,
            assistant_source_limit=version.assistant_source_limit,
        )
        session.add(sub)
        await session.flush()
        return Org(tenant_id, user.id, sub.id)


async def drop_org(org: Org) -> None:
    from app import db

    async with db.session_scope(staff=True) as session:
        for table in CLEANUP_TABLES:
            await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": org.tenant_id}
            )
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": org.tenant_id})
