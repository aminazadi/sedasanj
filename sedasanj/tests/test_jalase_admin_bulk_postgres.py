"""Staff bulk plan change and push for Jalase-Negar accounts (Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from tests.plan_helpers import requires_postgres, scratch  # noqa: F401
from tests.test_jalase_links_postgres import created, personal  # noqa: F401

from app import db
from app.errors import ApiError
from app.models import (
    ApiKey,
    JalasePushCampaign,
    JalasePushInstallation,
    JalasePushSettings,
    PlanVersion,
    Subscription,
)
from app.routers import admin_users
from app.services import jalase_accounts, ratelimit
from app.services.api_scopes import MOBILE_KEY_SCOPES

pytestmark = requires_postgres


async def plan_code_of(tenant_id: UUID) -> str:
    async with db.session_scope(staff=True) as session:
        row = (
            await session.execute(select(Subscription).where(Subscription.tenant_id == tenant_id))
        ).scalar_one()
        version = await session.get(PlanVersion, row.plan_version_id)
        assert version is not None
        from app.models import Plan

        plan = await session.get(Plan, version.plan_id)
        assert plan is not None
        return plan.code


async def test_staff_can_move_an_account_between_jalase_plans(created: list[UUID]) -> None:  # noqa: F811
    me = await personal(created)
    now = datetime.now(UTC)
    async with db.session_scope(staff=True) as session:
        assert await jalase_accounts.admin_set_plan(
            session, tenant_id=me[0], plan_code="jn_bronze", period_days=30, now=now
        )
        assert not await jalase_accounts.admin_set_plan(
            session, tenant_id=me[0], plan_code="jn_bronze", period_days=30, now=now
        )
    assert await plan_code_of(me[0]) == "jn_bronze"
    async with db.session_scope(staff=True) as session:
        row = (
            await session.execute(select(Subscription).where(Subscription.tenant_id == me[0]))
        ).scalar_one()
        assert timedelta(days=29) < row.period_end - now < timedelta(days=31)
        await jalase_accounts.admin_set_plan(
            session, tenant_id=me[0], plan_code="jn_free", period_days=30, now=now
        )
    assert await plan_code_of(me[0]) == "jn_free"
    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as unknown:
            await jalase_accounts.admin_set_plan(
                session, tenant_id=me[0], plan_code="no_such_plan", period_days=30, now=now
            )
    assert unknown.value.code == "plan_not_found"


async def test_push_goes_only_to_the_chosen_users_devices(
    created: list[UUID],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_limit(*_: object, **__: object) -> None:
        return None

    # The rate limiter keeps a Redis client bound to this test's event loop; later tests must
    # not inherit it.
    monkeypatch.setattr(ratelimit, "enforce", no_limit)
    mine = await personal(created)
    other = await personal(created)
    installs: list[UUID] = []
    async with db.session_scope(staff=True) as session:
        settings = await session.get(JalasePushSettings, 1)
        if settings is None:
            session.add(JalasePushSettings(id=1, enabled=True, project="p", credentials="x"))
        else:
            settings.enabled, settings.credentials = True, "x"
        for tenant_id, user_id in (mine, other):
            key = ApiKey(
                tenant_id=tenant_id,
                user_id=user_id,
                kind="mobile",
                label="گوشی",
                archive_format="gzip",
                key_prefix=uuid4().hex[:12],
                key_hash=uuid4().hex,
                scopes=list(MOBILE_KEY_SCOPES),
            )
            session.add(key)
            await session.flush()
            install = JalasePushInstallation(
                id=uuid4(),
                secret_hash="s",
                token_hash=uuid4().hex,
                token="t",
                mobile_key_id=key.id,
                version="1.0.0",
                channel="stable",
                enabled=True,
                seen_at=datetime.now(UTC),
            )
            session.add(install)
            installs.append(install.id)
    payload = admin_users.BulkRequest(
        action="push", dry_run=False, push_title="سلام", push_body="خبر تازه"
    )
    staff = SimpleNamespace(id=uuid4())
    campaigns_before = 0
    try:
        async with db.session_scope(staff=True) as session:
            sent = await admin_users._push_to_users(session, staff, [mine[1]], payload)
            assert sent == 1
            campaigns = (await session.execute(select(JalasePushCampaign))).scalars().all()
            targeted = [
                c
                for c in campaigns
                if c.payload["audience"].get("device_ids") == [str(installs[0])]
            ]
            assert len(targeted) == 1 and campaigns_before == 0
    finally:
        async with db.session_scope(staff=True) as session:
            await session.execute(
                delete(JalasePushCampaign).where(JalasePushCampaign.actor_id == staff.id)
            )
            await session.execute(
                delete(JalasePushInstallation).where(JalasePushInstallation.id.in_(installs))
            )
