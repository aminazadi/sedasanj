"""Plan catalog rules: publish, retire, update and listing (WP-5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from plan_helpers import requires_postgres, scratch
from sqlalchemy import text

pytestmark = requires_postgres
__all__ = ["scratch"]


def staff() -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(id=None)


def req() -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


def payload(**overrides: object) -> Any:
    from app.routers.commerce import PlanVersionCreate

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
    return PlanVersionCreate(**values)  # type: ignore[arg-type]


@pytest.fixture()
async def plan_code(scratch: None) -> AsyncIterator[str]:
    from app import db
    from app.models import Plan

    code = f"t_{uuid4().hex[:8]}"
    async with db.session_scope(staff=True) as session:
        session.add(Plan(code=code, name="catalog test", active=True, public=False))
    yield code
    async with db.session_scope(staff=True) as session:
        await session.execute(
            text(
                "DELETE FROM plan_versions WHERE plan_id IN (SELECT id FROM plans WHERE code = :c)"
            ),
            {"c": code},
        )
        await session.execute(text("DELETE FROM plans WHERE code = :c"), {"c": code})


async def _draft(code: str, **overrides: object) -> Any:
    from app import db
    from app.routers.commerce import create_plan_version

    async with db.session_scope(staff=True) as session:
        return await create_plan_version(code, payload(**overrides), req(), staff(), session)


async def _publish(version_id: Any, **extra: object) -> Any:
    from app import db
    from app.routers.commerce import PlanPublish, publish_plan_version

    async with db.session_scope(staff=True) as session:
        return await publish_plan_version(
            version_id, PlanPublish(reason="test", **extra), req(), staff(), session
        )


async def test_publish_requires_a_price_for_a_sellable_plan(plan_code: str) -> None:
    from uuid import UUID

    from app.errors import ApiError

    draft = await _draft(plan_code, annual_price_toman=0)
    with pytest.raises(ApiError) as caught:
        await _publish(UUID(draft["id"]))
    assert caught.value.code == "invalid_request"


async def test_publish_retires_the_previous_live_version(plan_code: str) -> None:
    from uuid import UUID

    from app import db
    from app.models import PlanVersion

    first = await _draft(plan_code)
    await _publish(UUID(first["id"]))
    second = await _draft(plan_code)
    await _publish(UUID(second["id"]))
    async with db.session_scope(staff=True) as session:
        old = await session.get(PlanVersion, UUID(first["id"]))
        new = await session.get(PlanVersion, UUID(second["id"]))
        assert old is not None and new is not None
        assert (old.status, new.status) == ("retired", "published")


async def test_publish_rejects_a_past_effective_date(plan_code: str) -> None:
    from datetime import UTC, datetime, timedelta
    from uuid import UUID

    from app.errors import ApiError

    draft = await _draft(plan_code)
    with pytest.raises(ApiError):
        await _publish(UUID(draft["id"]), effective_at=datetime.now(UTC) - timedelta(days=2))


async def test_retiring_the_only_live_version_needs_force(plan_code: str) -> None:
    from uuid import UUID

    from app import db
    from app.errors import ApiError
    from app.routers.commerce import PlanRetire, retire_plan_version

    live = await _draft(plan_code)
    await _publish(UUID(live["id"]))
    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as caught:
            await retire_plan_version(
                UUID(live["id"]), PlanRetire(reason="stop"), req(), staff(), session
            )
        assert caught.value.code == "plan_in_use"
        out = await retire_plan_version(
            UUID(live["id"]), PlanRetire(reason="stop", force=True), req(), staff(), session
        )
        assert out["status"] == "retired"


async def test_system_plans_cannot_be_deactivated(scratch: None) -> None:
    from app import db
    from app.errors import ApiError
    from app.routers.commerce import PlanUpdate, update_plan

    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as caught:
            await update_plan(
                "demo", PlanUpdate(reason="no way", active=False), req(), staff(), session
            )
        assert caught.value.code == "plan_in_use"


async def test_plan_without_versions_is_listed(plan_code: str) -> None:
    from app import db
    from app.routers.commerce import admin_plans

    async with db.session_scope(staff=True) as session:
        listing = await admin_plans(staff(), session, cursor=0, limit=200)
    mine = [item for item in listing["items"] if item["code"] == plan_code]
    assert len(mine) == 1
    assert mine[0]["id"] is None and mine[0]["subscription_count"] == 0


async def test_demo_is_a_trial_and_not_sellable(scratch: None) -> None:
    from sqlalchemy import select

    from app import db
    from app.models import Plan

    async with db.session_scope(staff=True) as session:
        demo = (await session.execute(select(Plan).where(Plan.code == "demo"))).scalar_one()
        assert demo.is_trial and not demo.sellable


async def test_inactive_subscription_has_its_own_error_code() -> None:
    from app.errors import ERROR_STATUS, RETRYABLE_CODES

    assert ERROR_STATUS["subscription_inactive"] == 402
    assert "subscription_inactive" in RETRYABLE_CODES
