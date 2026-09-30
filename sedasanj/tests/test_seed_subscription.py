from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from scripts.seed import _ensure_legacy_subscription


class ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


@pytest.mark.asyncio
async def test_seed_creates_missing_legacy_subscription() -> None:
    version = SimpleNamespace(
        id=uuid4(),
        assistant_tier="advanced",
        assistant_monthly_messages=2_147_483_647,
        assistant_source_limit=50,
        assistant_model=None,
    )
    tenant = SimpleNamespace(
        id=uuid4(),
        created_at=datetime.now(UTC),
        max_operators=25,
        price_per_minute_toman=2_000,
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[ScalarResult(None), ScalarResult(version)]
        ),
        add=Mock(),
    )

    created = await _ensure_legacy_subscription(session, tenant)

    assert created is True
    subscription = session.add.call_args.args[0]
    assert subscription.tenant_id == tenant.id
    assert subscription.status == "active"
    assert subscription.billing_period == "legacy"
    assert subscription.assistant_monthly_messages == 2_147_483_647


@pytest.mark.asyncio
async def test_seed_preserves_existing_subscription() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[ScalarResult(uuid4())]),
        add=Mock(),
    )

    created = await _ensure_legacy_subscription(
        session,
        SimpleNamespace(id=uuid4()),
    )

    assert created is False
    session.add.assert_not_called()
