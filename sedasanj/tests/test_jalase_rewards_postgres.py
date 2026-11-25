"""Jalase-Negar levels, badges, the monthly gift cap and friend invites (PAYMENT_TEST_DSN)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from tests.plan_helpers import requires_postgres, scratch  # noqa: F401

from app import db
from app.errors import ApiError
from app.models import (
    AuditEvent,
    JalaseAchievement,
    JalaseInviteRedemption,
    Meeting,
    MeetingDocument,
    StaffUser,
    Tenant,
    TokenGrant,
    User,
)
from app.routers import admin_jalase_achievements as admin_router
from app.services import jalase_accounts, jalase_rewards

pytestmark = requires_postgres

TENANT_TABLES = (
    "api_keys",
    "audit_events",
    "jalase_earned_achievements",
    "jalase_xp_events",
    "meeting_documents",
    "meetings",
    "token_grants",
    "ledger_entries",
    "credit_grants",
    "tenant_balance_cache",
    "trial_claims",
    "subscriptions",
    "users",
)


def test_levels_grow_with_xp() -> None:
    assert jalase_rewards.level_for(0) == (1, 0, 25)
    assert jalase_rewards.level_for(24)[0] == 1
    assert jalase_rewards.level_for(25) == (2, 25, 100)
    assert jalase_rewards.level_for(100)[0] == 3


def test_streak_counts_consecutive_weeks_and_forgives_the_current_one() -> None:
    now = datetime(2026, 11, 18, 10, tzinfo=UTC)  # a Wednesday
    week = timedelta(days=7)
    assert jalase_rewards.streak_weeks([], now) == 0
    assert jalase_rewards.streak_weeks([now - week, now - 2 * week], now) == 2
    assert jalase_rewards.streak_weeks([now, now - week, now - 2 * week], now) == 3
    assert jalase_rewards.streak_weeks([now - 2 * week], now) == 0  # a missed week resets it


@pytest.fixture()
async def created(scratch: None) -> AsyncIterator[list[UUID]]:  # noqa: F811
    tenants: list[UUID] = []
    yield tenants
    async with db.session_scope(staff=True) as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        for tenant_id in tenants:
            await session.execute(
                text(
                    "DELETE FROM jalase_invite_redemptions "
                    "WHERE invitee_tenant_id = :t OR inviter_tenant_id = :t"
                ),
                {"t": tenant_id},
            )
            await session.execute(
                text("DELETE FROM jalase_invite_codes WHERE tenant_id = :t"), {"t": tenant_id}
            )
            for table in TENANT_TABLES:
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM jalase_achievements WHERE code LIKE 'test_%'"))
        await session.execute(
            text(
                "DELETE FROM platform_settings "
                "WHERE key IN ('jalase_reward_cap_percent', 'jalase_invite_tokens')"
            )
        )


async def account(created: list[UUID], *, signup_ip: str | None = None) -> UUID:
    async with db.session_scope(staff=True) as session:
        tenant, _ = await jalase_accounts.create_personal_account(
            session, mobile="09" + str(uuid4().int)[:9], display_name="سارا", ip="127.0.0.1"
        )
        created.append(tenant.id)
        if signup_ip:
            session.add(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_type="user",
                    action="jalase.signup",
                    ip=signup_ip,
                )
            )
        return tenant.id


async def add_meetings(tenant_id: UUID, count: int, *, documents: int = 0) -> None:
    async with db.session_scope(staff=True) as session:
        user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_id))
        ).scalar_one()
        for index in range(count):
            meeting = Meeting(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                client_meeting_id=uuid4(),
                title=f"جلسه {index}",
                status="complete",
                started_at=datetime.now(UTC),
            )
            session.add(meeting)
            await session.flush()
            if index < documents:
                session.add(
                    MeetingDocument(
                        tenant_id=tenant_id,
                        meeting_id=meeting.id,
                        output_type_code=f"cat_{index % 3}",
                        output_type_version=1,
                        status="done",
                    )
                )


async def grants(tenant_id: UUID, source: str) -> list[int]:
    async with db.session_scope(staff=True) as session:
        rows = await session.execute(
            select(TokenGrant.total_tokens).where(
                TokenGrant.tenant_id == tenant_id, TokenGrant.source == source
            )
        )
        return sorted(rows.scalars().all())


async def test_a_badge_is_earned_once_and_pays_gift_tokens(created: list[UUID]) -> None:
    tenant_id = await account(created)
    assert await jalase_rewards.evaluate(tenant_id) == []
    await add_meetings(tenant_id, 1)
    newly = await jalase_rewards.evaluate(tenant_id)
    assert [item["code"] for item in newly] == ["first_meeting"]
    assert newly[0]["reward_tokens"] == 5_000 and newly[0]["reward_skipped"] is False
    assert await jalase_rewards.evaluate(tenant_id) == []  # never twice
    assert await grants(tenant_id, "reward") == [5_000]
    async with db.session_scope(staff=True) as session:
        grant = (
            await session.execute(select(TokenGrant).where(TokenGrant.tenant_id == tenant_id))
        ).scalar_one()
    assert grant.expires_at is not None and grant.expires_at > datetime.now(UTC) + timedelta(
        days=55
    )


async def test_progress_reports_level_badges_and_gift_allowance(created: list[UUID]) -> None:
    tenant_id = await account(created)
    await add_meetings(tenant_id, 3, documents=3)
    await jalase_rewards.evaluate(tenant_id)
    shown = await jalase_rewards.progress(tenant_id)
    assert shown["xp"] == 3 * 10 + 3 * 5
    assert shown["level"] == 2 and shown["next_level_xp"] == 100
    earned = {b["code"] for b in shown["badges"] if b["earned"]}
    assert {"first_meeting", "first_document", "three_categories"} <= earned
    locked = next(b for b in shown["badges"] if b["code"] == "five_meetings")
    assert (locked["current"], locked["threshold"], locked["earned"]) == (3, 5, False)
    assert shown["gift"]["limit_hours"] == 0.6  # 20% of the free plan's 3 hours
    assert {b["code"] for b in shown["newly_earned"]} == earned


async def test_gift_tokens_stop_at_the_monthly_cap(created: list[UUID]) -> None:
    tenant_id = await account(created)
    # Free plan: 120k tokens, 20% cap = 24k.  first_meeting 5k + first_document 5k +
    # five_meetings 10k = 20k; three_categories wants 10k but only 4k is left.
    await add_meetings(tenant_id, 5, documents=5)
    newly = {item["code"]: item for item in await jalase_rewards.evaluate(tenant_id)}
    assert sum(item["reward_tokens"] for item in newly.values()) == 24_000
    skipped = [code for code, item in newly.items() if item["reward_skipped"]]
    assert skipped, "at least one badge is cut by the cap"
    assert all(code in newly for code in ("first_meeting", "five_meetings"))
    assert sum(await grants(tenant_id, "reward")) == 24_000
    # The badge itself is kept even when its gift was cut.
    shown = await jalase_rewards.progress(tenant_id)
    assert shown["gift"]["left_hours"] == 0.0


async def test_a_zero_cap_turns_gifts_off_but_keeps_badges(created: list[UUID]) -> None:
    tenant_id = await account(created)
    async with db.session_scope(staff=True) as session:
        await session.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES "
                "('jalase_reward_cap_percent', '0') ON CONFLICT (key) DO UPDATE SET value='0'"
            )
        )
    await add_meetings(tenant_id, 1)
    newly = await jalase_rewards.evaluate(tenant_id)
    assert newly[0]["code"] == "first_meeting" and newly[0]["reward_tokens"] == 0
    assert await grants(tenant_id, "reward") == []


async def test_friend_invite_rewards_both_sides_once(created: list[UUID]) -> None:
    inviter = await account(created)
    invitee = await account(created)
    code = (await jalase_rewards.invite_info(inviter))["code"]
    assert (await jalase_rewards.invite_info(inviter))["code"] == code  # stable
    with pytest.raises(ApiError) as own:
        await jalase_rewards.redeem(inviter, code)
    assert own.value.code == "invite_invalid"
    with pytest.raises(ApiError) as bad:
        await jalase_rewards.redeem(invitee, "ZZZZZZZZ")
    assert bad.value.code == "invite_invalid"
    await jalase_rewards.redeem(invitee, code.lower())
    assert await grants(invitee, "invite") == [20_000]
    # Both sides are paid by the redemption itself; the inviter need not open the app.
    assert await grants(inviter, "invite") == [20_000]
    await jalase_rewards.progress(inviter)  # idempotent
    await jalase_rewards.progress(invitee)
    assert await grants(inviter, "invite") == [20_000]
    assert await grants(invitee, "invite") == [20_000]
    with pytest.raises(ApiError) as again:
        await jalase_rewards.redeem(invitee, code)
    assert again.value.code == "invite_not_allowed"
    assert (await jalase_rewards.invite_info(inviter))["joined"] == 1


async def test_invites_need_a_new_account_and_can_be_switched_off(created: list[UUID]) -> None:
    inviter = await account(created)
    old = await account(created)
    code = (await jalase_rewards.invite_info(inviter))["code"]
    async with db.session_scope(staff=True) as session:
        tenant = await session.get(Tenant, old)
        assert tenant is not None
        tenant.created_at = datetime.now(UTC) - timedelta(days=10)
    with pytest.raises(ApiError) as late:
        await jalase_rewards.redeem(old, code)
    assert late.value.code == "invite_not_allowed"
    async with db.session_scope(staff=True) as session:
        await session.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES "
                "('jalase_invite_tokens', '0') ON CONFLICT (key) DO UPDATE SET value='0'"
            )
        )
    fresh = await account(created)
    with pytest.raises(ApiError) as off:
        await jalase_rewards.redeem(fresh, code)
    assert off.value.code == "invite_disabled"


async def test_an_inviter_is_limited_per_month(created: list[UUID]) -> None:
    inviter = await account(created)
    code = (await jalase_rewards.invite_info(inviter))["code"]
    for _ in range(jalase_rewards.INVITES_PER_MONTH):
        await jalase_rewards.redeem(await account(created), code)
    with pytest.raises(ApiError) as capped:
        await jalase_rewards.redeem(await account(created), code)
    assert capped.value.code == "invite_not_allowed"


async def test_many_invitees_from_one_network_stop_at_the_limit(created: list[UUID]) -> None:
    inviter = await account(created)
    code = (await jalase_rewards.invite_info(inviter))["code"]
    for _ in range(jalase_rewards.INVITES_PER_IP_PER_MONTH):
        await jalase_rewards.redeem(await account(created, signup_ip="203.0.113.9"), code)
    with pytest.raises(ApiError) as crowded:
        await jalase_rewards.redeem(await account(created, signup_ip="203.0.113.9"), code)
    assert crowded.value.code == "invite_not_allowed" and "پشتیبانی" in crowded.value.message
    # A different network is not affected.
    await jalase_rewards.redeem(await account(created, signup_ip="198.51.100.4"), code)


async def test_admin_edits_badges_and_gifts(created: list[UUID]) -> None:
    async with db.session_scope(staff=True) as session:
        staff = StaffUser(
            email=f"jn-ach-{uuid4().hex[:8]}@example.com", password_hash="x", role="super_admin"
        )
        session.add(staff)
        await session.flush()
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
        made = await admin_router.create_achievement(
            admin_router.AchievementCreate(
                code="test_badge",
                title_fa="نشان آزمایشی",
                description_fa="برای آزمون",
                metric="meetings",
                threshold=2,
                reward_tokens=7_000,
            ),
            request,  # type: ignore[arg-type]
            staff,  # type: ignore[arg-type]
            session,
        )
        with pytest.raises(ApiError):
            await admin_router.create_achievement(
                admin_router.AchievementCreate(
                    code="test_badge",
                    title_fa="تکراری",
                    description_fa="تکراری",
                    metric="meetings",
                    threshold=2,
                    reward_tokens=1,
                ),
                request,  # type: ignore[arg-type]
                staff,  # type: ignore[arg-type]
                session,
            )
        changed = await admin_router.update_achievement(
            UUID(made["id"]),
            admin_router.AchievementUpdate(reward_tokens=9_000, active=False),
            request,  # type: ignore[arg-type]
            staff,  # type: ignore[arg-type]
            session,
        )
        assert (changed["reward_tokens"], changed["active"]) == (9_000, False)
        await session.delete(await session.get(JalaseAchievement, UUID(made["id"])))
        await session.flush()
        await session.execute(text("DELETE FROM audit_events WHERE actor_id = :s"), {"s": staff.id})
        await session.delete(staff)


async def test_opening_progress_awards_nothing(created: list[UUID]) -> None:
    """The progress screen is a read; the gift is paid when the meeting finishes."""
    tenant_id = await account(created)
    await add_meetings(tenant_id, 1)
    shown = await jalase_rewards.progress(tenant_id)
    assert shown["newly_earned"] == []
    assert not any(badge["earned"] for badge in shown["badges"])
    assert await grants(tenant_id, "reward") == []
    # The event path is the one that pays, and it pays once.
    assert [item["code"] for item in await jalase_rewards.evaluate(tenant_id)] == ["first_meeting"]
    assert await grants(tenant_id, "reward") == [5_000]
    assert [
        item["code"] for item in (await jalase_rewards.progress(tenant_id))["newly_earned"]
    ] == ["first_meeting"]
    await jalase_rewards.mark_seen(tenant_id)
    assert (await jalase_rewards.progress(tenant_id))["newly_earned"] == []


async def test_an_earned_badge_stays_visible_after_it_is_deactivated(
    created: list[UUID],
) -> None:
    tenant_id = await account(created)
    async with db.session_scope(staff=True) as session:
        session.add(
            JalaseAchievement(
                code="test_inactive_badge",
                title_fa="نشان آزمایشی",
                description_fa="برای آزمون",
                metric="meetings",
                threshold=1,
                reward_tokens=0,
                sort_order=999,
            )
        )
    await add_meetings(tenant_id, 1)
    await jalase_rewards.evaluate(tenant_id)
    async with db.session_scope(staff=True) as session:
        await session.execute(
            text("UPDATE jalase_achievements SET active = false WHERE code = 'test_inactive_badge'")
        )
    shown = await jalase_rewards.progress(tenant_id)
    badge = next(item for item in shown["badges"] if item["code"] == "test_inactive_badge")
    assert badge["earned"] is True and badge["active"] is False


async def test_a_long_streak_badge_is_reachable(created: list[UUID]) -> None:
    """The streak window follows the longest active badge instead of a hidden 200-day cap."""
    tenant_id = await account(created)
    async with db.session_scope(staff=True) as session:
        session.add(
            JalaseAchievement(
                code="test_streak_40",
                title_fa="چهل هفته",
                description_fa="برای آزمون",
                metric="streak_weeks",
                threshold=40,
                reward_tokens=0,
                sort_order=998,
            )
        )
    now = datetime.now(UTC)
    async with db.session_scope(staff=True) as session:
        user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_id))
        ).scalar_one()
        for index in range(40):
            session.add(
                Meeting(
                    tenant_id=tenant_id,
                    owner_user_id=user_id,
                    client_meeting_id=uuid4(),
                    status="complete",
                    started_at=now - timedelta(weeks=index),
                    created_at=now - timedelta(weeks=index),
                )
            )
    newly = {item["code"] for item in await jalase_rewards.evaluate(tenant_id, now)}
    assert "test_streak_40" in newly


async def test_concurrent_invite_settlement_pays_once(created: list[UUID]) -> None:
    inviter = await account(created)
    invitee = await account(created)
    async with db.session_scope(staff=True) as session:
        session.add(
            JalaseInviteRedemption(
                invitee_tenant_id=invitee,
                inviter_tenant_id=inviter,
                reward_tokens=20_000,
            )
        )
    now = datetime.now(UTC)
    await asyncio.gather(
        *(jalase_rewards.settle_invites(inviter, now) for _ in range(4)),
        return_exceptions=False,
    )
    assert await grants(inviter, "invite") == [20_000]
