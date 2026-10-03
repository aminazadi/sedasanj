from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.models import Subscription, Tenant
from app.routers import admin
from app.schemas import TenantCreate
from app.services.payments import _organization_price_per_minute


@pytest.mark.asyncio
async def test_create_tenant_preserves_organization_specific_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    created: list[object] = []
    plan_version = SimpleNamespace(
        id=uuid4(),
        base_operators=3,
        overage_price_per_minute_toman=2_000,
        assistant_tier="simple",
        assistant_monthly_messages=50,
        assistant_source_limit=8,
        assistant_model=None,
    )
    result = MagicMock()
    result.one_or_none.return_value = (SimpleNamespace(), plan_version)
    async def flush() -> None:
        for item in created:
            if isinstance(item, Tenant):
                item.id = tenant_id
                item.created_at = datetime.now(UTC)

    session = SimpleNamespace(
        add=created.append,
        flush=flush,
        execute=AsyncMock(return_value=result),
    )
    monkeypatch.setattr(admin.audit, "record", AsyncMock())
    monkeypatch.setattr(admin, "hash_password", lambda _: "hashed")

    payload = TenantCreate(
        name="Organization",
        price_per_minute_toman=7_500,
        admin_email="admin@example.com",
        admin_password="password123",
        plan_code="legacy_custom",
        billing_period="legacy",
    )
    request = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})
    staff = SimpleNamespace(id=uuid4())

    output = await admin.create_tenant(payload, request, staff, session)

    tenant = next(item for item in created if isinstance(item, Tenant))
    subscription = next(item for item in created if isinstance(item, Subscription))
    assert output.price_per_minute_toman == 7_500
    assert tenant.price_per_minute_toman == 7_500
    assert subscription.price_per_minute_toman == 7_500
    assert subscription.price_per_minute_toman != plan_version.overage_price_per_minute_toman


def test_plan_changes_preserve_organization_specific_price() -> None:
    tenant = SimpleNamespace(price_per_minute_toman=7_500)
    subscription = SimpleNamespace(price_per_minute_toman=6_000)
    version = SimpleNamespace(overage_price_per_minute_toman=2_000)

    assert _organization_price_per_minute(tenant, subscription, version) == 7_500
