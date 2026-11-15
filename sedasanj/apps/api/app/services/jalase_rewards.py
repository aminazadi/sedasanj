"""Jalase-Negar gamification: XP and levels, admin-defined badges, gift tokens and invites.

Progress is derived from the user's own data (meetings and finished documents), so it cannot
drift.  Gift tokens are `token_grants` rows (sources ``reward`` and ``invite``, 60-day expiry).
Badge gifts count against one monthly cap, a share of the plan's token allowance that the admin
sets (`jalase_reward_cap_percent`), so rewards cannot become a way to use the product for free.
Invite rewards are a fixed amount per friend with their own limit (INVITES_PER_MONTH).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from math import isqrt
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import control_session_scope, session_scope
from app.errors import ApiError
from app.models import (
    JalaseAchievement,
    JalaseEarnedAchievement,
    JalaseInviteCode,
    JalaseInviteRedemption,
    Meeting,
    MeetingDocument,
    Tenant,
    TokenGrant,
)
from app.services import audit, entitlements, platform, token_quota
from app.services.quotas import quota_period_start

PRODUCT = "jalase_negar"
REWARD_TTL_DAYS = 60
XP_PER_MEETING = 10
XP_PER_DOCUMENT = 5
INVITES_PER_MONTH = 10  # rewarded invites an inviter can collect per month
INVITEE_WINDOW_DAYS = 7  # a code can only be used by an account this new
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def level_for(xp: int) -> tuple[int, int, int]:
    """(level, xp at the start of the level, xp needed for the next one)."""
    level = 1 + isqrt(max(0, xp) // 25)
    return level, 25 * (level - 1) ** 2, 25 * level**2


def streak_weeks(starts: list[datetime], now: datetime) -> int:
    """Consecutive ISO weeks with a meeting, ending this week or last week."""
    weeks = {(s.isocalendar().year, s.isocalendar().week) for s in starts}
    cursor = now.date()
    if (cursor.isocalendar().year, cursor.isocalendar().week) not in weeks:
        cursor -= timedelta(days=7)  # this week is not over: last week still counts
    streak = 0
    while (cursor.isocalendar().year, cursor.isocalendar().week) in weeks:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


async def metrics(session: AsyncSession, tenant_id: UUID, now: datetime) -> dict[str, int]:
    meetings = int(
        (
            await session.execute(
                select(func.count()).select_from(Meeting).where(Meeting.tenant_id == tenant_id)
            )
        ).scalar_one()
    )
    documents, categories = (
        await session.execute(
            select(func.count(), func.count(func.distinct(MeetingDocument.output_type_code)))
            .select_from(MeetingDocument)
            .where(MeetingDocument.tenant_id == tenant_id, MeetingDocument.status == "done")
        )
    ).one()
    starts = (
        (
            await session.execute(
                select(Meeting.started_at).where(
                    Meeting.tenant_id == tenant_id,
                    Meeting.started_at >= now - timedelta(days=200),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "meetings": meetings,
        "documents": int(documents),
        "categories": int(categories),
        "streak_weeks": streak_weeks(list(starts), now),
    }


async def gift_cap(session: AsyncSession, tenant_id: UUID, now: datetime) -> dict[str, int]:
    """This month's badge-gift limit, what was already given and what is left."""
    percent = await platform.jalase_reward_cap_percent(session)
    value = await entitlements.effective(session, tenant_id)
    if value.llm_monthly_tokens is None or value.period_start is None:
        return {"limit": 0, "used": 0, "left": 0}
    limit = value.llm_monthly_tokens * percent // 100
    start = quota_period_start(value.period_start, now)
    used = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(TokenGrant.total_tokens), 0)).where(
                    TokenGrant.tenant_id == tenant_id,
                    TokenGrant.source == "reward",
                    TokenGrant.created_at >= start,
                )
            )
        ).scalar_one()
    )
    return {"limit": limit, "used": used, "left": max(0, limit - used)}


async def _give(
    session: AsyncSession, tenant_id: UUID, source: str, tokens: int, now: datetime
) -> int:
    """Grant gift tokens; badge gifts (``reward``) are cut to what the monthly cap leaves."""
    amount = tokens
    if source == "reward":
        amount = min(tokens, (await gift_cap(session, tenant_id, now))["left"])
    if amount <= 0:
        return 0
    session.add(
        TokenGrant(
            tenant_id=tenant_id,
            source=source,
            total_tokens=amount,
            remaining_tokens=amount,
            expires_at=now + timedelta(days=REWARD_TTL_DAYS),
        )
    )
    return amount


async def evaluate(tenant_id: UUID, now: datetime | None = None) -> list[dict[str, Any]]:
    """Award every badge the account now qualifies for; returns the newly earned ones."""
    now = now or datetime.now(UTC)
    async with control_session_scope() as control:
        catalogue = (
            (
                await control.execute(
                    select(JalaseAchievement)
                    .where(JalaseAchievement.active.is_(True))
                    .order_by(JalaseAchievement.sort_order, JalaseAchievement.code)
                )
            )
            .scalars()
            .all()
        )
    newly: list[dict[str, Any]] = []
    async with session_scope(tenant_id) as session:
        await token_quota.lock_tenant(session, tenant_id)
        values = await metrics(session, tenant_id, now)
        earned = set(
            (
                await session.execute(
                    select(JalaseEarnedAchievement.achievement_code).where(
                        JalaseEarnedAchievement.tenant_id == tenant_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for badge in catalogue:
            if badge.code in earned or values.get(badge.metric, 0) < badge.threshold:
                continue
            gift = await _give(session, tenant_id, "reward", badge.reward_tokens, now)
            session.add(
                JalaseEarnedAchievement(
                    tenant_id=tenant_id,
                    achievement_code=badge.code,
                    reward_tokens=gift,
                    earned_at=now,
                )
            )
            newly.append(
                {
                    "code": badge.code,
                    "title": badge.title_fa,
                    "reward_tokens": gift,
                    "reward_skipped": gift < badge.reward_tokens,
                }
            )
    return newly


async def progress(tenant_id: UUID, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    newly = await evaluate(tenant_id, now)
    await settle_invites(tenant_id, now)
    async with control_session_scope() as control:
        catalogue = (
            (
                await control.execute(
                    select(JalaseAchievement)
                    .where(JalaseAchievement.active.is_(True))
                    .order_by(JalaseAchievement.sort_order, JalaseAchievement.code)
                )
            )
            .scalars()
            .all()
        )
        per_hour = await platform.jalase_tokens_per_hour(control)
    async with session_scope(tenant_id) as session:
        values = await metrics(session, tenant_id, now)
        earned = {
            row.achievement_code: row
            for row in (
                await session.execute(
                    select(JalaseEarnedAchievement).where(
                        JalaseEarnedAchievement.tenant_id == tenant_id
                    )
                )
            )
            .scalars()
            .all()
        }
        cap = await gift_cap(session, tenant_id, now)
    xp = values["meetings"] * XP_PER_MEETING + values["documents"] * XP_PER_DOCUMENT
    level, floor_xp, next_xp = level_for(xp)
    badges = []
    for badge in catalogue:
        row = earned.get(badge.code)
        badges.append(
            {
                "code": badge.code,
                "title": badge.title_fa,
                "description": badge.description_fa,
                "metric": badge.metric,
                "threshold": badge.threshold,
                "current": min(values.get(badge.metric, 0), badge.threshold),
                "reward_tokens": badge.reward_tokens,
                "earned": row is not None,
                "earned_at": row.earned_at if row else None,
            }
        )
    return {
        "xp": xp,
        "level": level,
        "level_xp": floor_xp,
        "next_level_xp": next_xp,
        "metrics": values,
        "badges": badges,
        "newly_earned": newly,
        "gift": {
            "limit_hours": round(cap["limit"] / max(1, per_hour), 1),
            "used_hours": round(cap["used"] / max(1, per_hour), 1),
            "left_hours": round(cap["left"] / max(1, per_hour), 1),
        },
    }


# ---- friend invites ---------------------------------------------------------------------


async def invite_info(tenant_id: UUID) -> dict[str, Any]:
    """The account's invite code (created on first use) and how many friends joined."""
    async with control_session_scope() as control:
        row = await control.get(JalaseInviteCode, tenant_id)
        if row is None:
            for _ in range(5):
                code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
                try:
                    async with control.begin_nested():
                        row = JalaseInviteCode(tenant_id=tenant_id, code=code)
                        control.add(row)
                        await control.flush()
                    break
                except IntegrityError:
                    row = None
            if row is None:
                raise ApiError("internal", "could not create an invite code; try again")
        joined = int(
            (
                await control.execute(
                    select(func.count())
                    .select_from(JalaseInviteRedemption)
                    .where(JalaseInviteRedemption.inviter_tenant_id == tenant_id)
                )
            ).scalar_one()
        )
        tokens = await platform.jalase_invite_tokens(control)
        per_hour = await platform.jalase_tokens_per_hour(control)
        return {
            "code": row.code,
            "joined": joined,
            "reward_hours": round(tokens / max(1, per_hour), 1),
            "enabled": tokens > 0,
        }


async def redeem(invitee_tenant_id: UUID, code: str, now: datetime | None = None) -> dict[str, Any]:
    """Use a friend's code once, within a week of signing up; both sides get gift tokens."""
    now = now or datetime.now(UTC)
    code = code.strip().upper()
    async with control_session_scope() as control:
        tokens = await platform.jalase_invite_tokens(control)
        if tokens <= 0:
            raise ApiError("invite_disabled", "دعوت دوستان فعلاً فعال نیست.")
        invitee = await control.get(Tenant, invitee_tenant_id)
        if invitee is None or invitee.product != PRODUCT:
            raise ApiError("forbidden", "این بخش فقط برای حساب شخصی جلسه‌نگار است.")
        if now - invitee.created_at > timedelta(days=INVITEE_WINDOW_DAYS):
            raise ApiError(
                "invite_not_allowed", "کد دعوت فقط تا یک هفته پس از ساخت حساب قابل استفاده است."
            )
        owner = (
            await control.execute(select(JalaseInviteCode).where(JalaseInviteCode.code == code))
        ).scalar_one_or_none()
        if owner is None:
            raise ApiError("invite_invalid", "کد دعوت درست نیست؛ آن را از دوستتان دوباره بگیرید.")
        if owner.tenant_id == invitee_tenant_id:
            raise ApiError("invite_invalid", "نمی‌توانید از کد دعوت خودتان استفاده کنید.")
        month_start = now - timedelta(days=30)
        rewarded = int(
            (
                await control.execute(
                    select(func.count())
                    .select_from(JalaseInviteRedemption)
                    .where(
                        JalaseInviteRedemption.inviter_tenant_id == owner.tenant_id,
                        JalaseInviteRedemption.redeemed_at >= month_start,
                    )
                )
            ).scalar_one()
        )
        if rewarded >= INVITES_PER_MONTH:
            raise ApiError(
                "invite_not_allowed", "این کد در این ماه به سقف دعوت رسیده است؛ بعداً امتحان کنید."
            )
        try:
            async with control.begin_nested():
                control.add(
                    JalaseInviteRedemption(
                        invitee_tenant_id=invitee_tenant_id,
                        inviter_tenant_id=owner.tenant_id,
                        reward_tokens=tokens,
                        redeemed_at=now,
                    )
                )
                await control.flush()
        except IntegrityError as error:
            raise ApiError(
                "invite_not_allowed", "برای این حساب قبلاً کد دعوت ثبت شده است."
            ) from error
        inviter_id = owner.tenant_id
    await settle_invites(invitee_tenant_id, now)
    await audit_redeem(invitee_tenant_id, inviter_id, tokens)
    return {"reward_hours": 0.0, "tokens": tokens}


async def audit_redeem(invitee: UUID, inviter: UUID, tokens: int) -> None:
    async with session_scope(invitee) as session:
        await audit.record(
            session,
            actor_type="system",
            tenant_id=invitee,
            action="jalase.invite_redeemed",
            payload={"inviter_tenant_id": str(inviter), "tokens": tokens},
        )


async def settle_invites(tenant_id: UUID, now: datetime) -> None:
    """Pay the pending invite rewards of this account (as invitee and as inviter)."""
    async with control_session_scope() as control:
        rows = (
            (
                await control.execute(
                    select(JalaseInviteRedemption).where(
                        (JalaseInviteRedemption.invitee_tenant_id == tenant_id)
                        | (JalaseInviteRedemption.inviter_tenant_id == tenant_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        pending = [
            (row.invitee_tenant_id, row.inviter_tenant_id, row.reward_tokens, side)
            for row in rows
            for side, done, owner in (
                ("invitee", row.invitee_granted, row.invitee_tenant_id),
                ("inviter", row.inviter_granted, row.inviter_tenant_id),
            )
            if not done and owner == tenant_id
        ]
    for invitee_id, inviter_id, tokens, side in pending:
        target = invitee_id if side == "invitee" else inviter_id
        async with session_scope(target) as session:
            await token_quota.lock_tenant(session, target)
            await _give(session, target, "invite", tokens, now)
        async with control_session_scope() as control:
            row = await control.get(JalaseInviteRedemption, invitee_id, with_for_update=True)
            if row is not None:
                if side == "invitee":
                    row.invitee_granted = True
                else:
                    row.inviter_granted = True
