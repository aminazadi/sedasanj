from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.services.billing import Balance
from app.services.entitlements import Entitlements, require_upload_consumption


def missing_entitlements() -> Entitlements:
    return Entitlements(None, "missing", 0, 2_000, "none", 0, 0, None, None, None)


@pytest.mark.asyncio
async def test_prepaid_credit_allows_upload_without_a_subscription() -> None:
    tenant_id = uuid4()
    with (
        patch(
            "app.services.entitlements.effective",
            new=AsyncMock(return_value=missing_entitlements()),
        ),
        patch(
            "app.services.entitlements.billing.get_balance",
            new=AsyncMock(return_value=Balance(seconds=36_000, toman=6_000_000)),
        ),
    ):
        value = await require_upload_consumption(
            AsyncMock(), tenant_id, price_per_minute_toman=10_000
        )

    assert value.status == "missing"
    assert value.price_per_minute_toman == 10_000


@pytest.mark.asyncio
async def test_upload_without_subscription_or_credit_is_rejected() -> None:
    tenant_id = uuid4()
    with (
        patch(
            "app.services.entitlements.effective",
            new=AsyncMock(return_value=missing_entitlements()),
        ),
        patch(
            "app.services.entitlements.billing.get_balance",
            new=AsyncMock(return_value=Balance(seconds=0, toman=0)),
        ),
        pytest.raises(ApiError, match="subscription is not active"),
    ):
        await require_upload_consumption(AsyncMock(), tenant_id, price_per_minute_toman=10_000)


@pytest.mark.asyncio
async def test_active_subscription_does_not_need_a_credit_balance() -> None:
    tenant_id = uuid4()
    active = Entitlements(
        uuid4(),
        "active",
        2,
        2_000,
        "simple",
        50,
        8,
        None,
        datetime.now(UTC) - timedelta(days=1),
        datetime.now(UTC) + timedelta(days=1),
    )
    with (
        patch("app.services.entitlements.effective", new=AsyncMock(return_value=active)),
        patch("app.services.entitlements.billing.get_balance", new=AsyncMock()) as get_balance,
    ):
        value = await require_upload_consumption(
            AsyncMock(), tenant_id, price_per_minute_toman=10_000
        )

    assert value is active
    get_balance.assert_not_awaited()
