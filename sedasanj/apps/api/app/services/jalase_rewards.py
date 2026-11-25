"""Jalase-Negar gamification: XP and levels, admin-defined badges, gift tokens and invites.

Progress is derived from the user's own data (finished meetings and documents), so it cannot
drift.  XP is recorded as events (`jalase_xp_events`) the first time a meeting or document
counts, so deleting one later does not lower the level.  Gift tokens are `token_grants` rows
(sources ``reward`` and ``invite``, 60-day expiry) and every grant carries a `source_id`, so a
retry or a race cannot pay the same gift twice.  Badge gifts count against one monthly cap, a
share of the plan's token allowance that the admin sets (`jalase_reward_cap_percent`), so rewards
cannot become a way to use the product for free.  Invite rewards are a fixed amount per friend
with their own limit (INVITES_PER_MONTH).

Badges are awarded when the event happens (a meeting completes, a document finishes), not when
the progress screen is opened; `progress()` only reads.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, date, datetime, timedelta
from math import isqrt
from typing import Any
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, literal, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import control_session_scope, session_scope
from app.errors import ApiError
from app.models import (
    AuditEvent,
    JalaseAchievement,
    JalaseEarnedAchievement,
    JalaseInviteCode,
    JalaseInviteRedemption,
    JalasePushCampaign,
    JalaseXpEvent,
    Meeting,
    MeetingDocument,
    Tenant,
    TokenGrant,
    User,
)
from app.services import audit, entitlements, jalase_push, platform, token_quota
from app.services.quotas import quota_period_start

logger = logging.getLogger(__name__)

PRODUCT = "jalase_negar"
REWARD_TTL_DAYS = 60
XP_PER_MEETING = 10
XP_PER_DOCUMENT = 5
INVITES_PER_IP_PER_MONTH = 3  # rewarded invitees that may sign up from one network address
INVITES_PER_MONTH = 10  # rewarded invites an inviter can collect per month
INVITEE_WINDOW_DAYS = 7  # a code can only be used by an account this new
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
STREAK_ZONE = ZoneInfo("Asia/Tehran")
STREAK_MAX_WEEKS = 52
REWARD_NAMESPACE = UUID("6f0c1f52-3f0a-4b0f-9a1e-0f3f0f7d1a11")


def level_for(xp: int) -> tuple[int, int, int]:
    """(level, xp at the start of the level, xp needed for the next one)."""
    level = 1 + isqrt(max(0, xp) // 25)
    return level, 25 * (level - 1) ** 2, 25 * level**2


def week_start(moment: datetime) -> date:
    """The Saturday that starts the week containing `moment`, in Tehran time."""
    local = moment.astimezone(STREAK_ZONE) if moment.tzinfo else moment.replace(tzinfo=UTC)
    day = local.date()
    return day - timedelta(days=(day.weekday() + 2) % 7)


def streak_weeks(starts: list[datetime], now: datetime) -> int:
    """Consecutive weeks (Saturday to Friday, Tehran time) with a meeting.

    The current week may still be in progress, so a streak that ended last week still counts.
    """
    weeks = {week_start(start) for start in starts}
    cursor = week_start(now)
    if cursor not in weeks:
        cursor -= timedelta(days=7)
    streak = 0
    while cursor in weeks:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


async def _streak_window_days(control: AsyncSession) -> int:
    """Enough history to measure the longest active streak badge, with one spare week."""
    longest = (
        await control.execute(
            select(func.max(JalaseAchievement.threshold)).where(
                JalaseAchievement.metric == "streak_weeks",
                JalaseAchievement.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    weeks = min(int(longest or 0), STREAK_MAX_WEEKS)
    return weeks * 7 + 14


async def _sync_xp_events(session: AsyncSession, tenant_id: UUID) -> None:
    """Record every finished meeting and document once; existing rows are left alone."""
    await session.execute(
        pg_insert(JalaseXpEvent)
        .from_select(
            ["tenant_id", "kind", "ref_id", "points"],
            select(
                Meeting.tenant_id,
                literal("meeting"),
                Meeting.id,
                literal(XP_PER_MEETING),
            ).where(Meeting.tenant_id == tenant_id, Meeting.status == "complete"),
        )
        .on_conflict_do_nothing()
    )
    await session.execute(
        pg_insert(JalaseXpEvent)
        .from_select(
            ["tenant_id", "kind", "ref_id", "points"],
            select(
                MeetingDocument.tenant_id,
                literal("document"),
                MeetingDocument.id,
                literal(XP_PER_DOCUMENT),
            ).where(MeetingDocument.tenant_id == tenant_id, MeetingDocument.status == "done"),
        )
        .on_conflict_do_nothing()
    )


async def _xp(session: AsyncSession, tenant_id: UUID) -> int:
    """XP from recorded events plus anything finished that has not been recorded yet.

    The second part keeps the number correct before the next `evaluate` run (and for a meeting
    that finished while the worker was down) without writing from a read-only request.
    """
    recorded = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(JalaseXpEvent.points), 0)).where(
                    JalaseXpEvent.tenant_id == tenant_id
                )
            )
        ).scalar_one()
    )
    meeting_events = select(JalaseXpEvent.ref_id).where(
        JalaseXpEvent.tenant_id == tenant_id, JalaseXpEvent.kind == "meeting"
    )
    document_events = select(JalaseXpEvent.ref_id).where(
        JalaseXpEvent.tenant_id == tenant_id, JalaseXpEvent.kind == "document"
    )
    unrecorded_meetings = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Meeting)
                .where(
                    Meeting.tenant_id == tenant_id,
                    Meeting.status == "complete",
                    Meeting.id.not_in(meeting_events),
                )
            )
        ).scalar_one()
    )
    unrecorded_documents = int(
        (
            await session.execute(
                select(func.count())
                .select_from(MeetingDocument)
                .where(
                    MeetingDocument.tenant_id == tenant_id,
                    MeetingDocument.status == "done",
                    MeetingDocument.id.not_in(document_events),
                )
            )
        ).scalar_one()
    )
    return recorded + unrecorded_meetings * XP_PER_MEETING + unrecorded_documents * XP_PER_DOCUMENT


async def metrics(
    session: AsyncSession, tenant_id: UUID, now: datetime, *, streak_days: int = 200
) -> dict[str, int]:
    meetings = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Meeting)
                .where(Meeting.tenant_id == tenant_id, Meeting.status == "complete")
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
    # `created_at` is the server's receive time; the app's `started_at` comes from the phone clock.
    starts = (
        (
            await session.execute(
                select(Meeting.created_at).where(
                    Meeting.tenant_id == tenant_id,
                    Meeting.status == "complete",
                    Meeting.created_at >= now - timedelta(days=streak_days),
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
    session: AsyncSession,
    tenant_id: UUID,
    source: str,
    tokens: int,
    now: datetime,
    *,
    source_id: UUID | None = None,
) -> int:
    """Grant gift tokens; badge gifts (``reward``) are cut to what the monthly cap leaves.

    A grant with the same ``(tenant, source, source_id)`` already present is a retry and pays
    nothing, so a failed transaction or two concurrent requests cannot double the gift.
    """
    amount = tokens
    if source == "reward":
        amount = min(tokens, (await gift_cap(session, tenant_id, now))["left"])
    if amount <= 0:
        return 0
    try:
        async with session.begin_nested():
            session.add(
                TokenGrant(
                    tenant_id=tenant_id,
                    source=source,
                    source_id=source_id,
                    total_tokens=amount,
                    remaining_tokens=amount,
                    expires_at=now + timedelta(days=REWARD_TTL_DAYS),
                )
            )
            await session.flush()
    except IntegrityError:
        return 0
    return amount


def _reward_source_id(tenant_id: UUID, code: str) -> UUID:
    return uuid5(REWARD_NAMESPACE, f"reward:{tenant_id}:{code}")


async def evaluate(
    tenant_id: UUID, now: datetime | None = None, *, notify: bool = True
) -> list[dict[str, Any]]:
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
        streak_days = await _streak_window_days(control)
    newly: list[dict[str, Any]] = []
    async with session_scope(tenant_id) as session:
        await token_quota.lock_tenant(session, tenant_id)
        await _sync_xp_events(session, tenant_id)
        values = await metrics(session, tenant_id, now, streak_days=streak_days)
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
            gift = await _give(
                session,
                tenant_id,
                "reward",
                badge.reward_tokens,
                now,
                source_id=_reward_source_id(tenant_id, badge.code),
            )
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
    if newly and notify:
        await _notify_badges(tenant_id, newly)
    return newly


async def _notify_badges(tenant_id: UUID, badges: list[dict[str, Any]]) -> None:
    """Send one push per new badge; a push failure must never undo the award."""
    try:
        async with control_session_scope() as control:
            config = await jalase_push.settings(control)
            if not config or not config.enabled or not config.credentials:
                return
            user_id = (
                await control.execute(select(User.id).where(User.tenant_id == tenant_id).limit(1))
            ).scalar_one_or_none()
            if user_id is None:
                return
            now = datetime.now(UTC)
            for badge in badges:
                message = jalase_push.Message(
                    kind="combined",
                    title="نشان جدید",
                    body=f"نشان «{badge['title']}» را گرفتید؛ از بخش «پیشرفت و دعوت» ببینید.",
                    destination="home",
                    data={"badge": badge["code"]},
                )
                audience = jalase_push.Audience(kind="user", user_id=user_id)
                control.add(
                    JalasePushCampaign(
                        id=uuid4(),
                        actor_id=user_id,
                        payload={
                            "audience": audience.model_dump(mode="json"),
                            "message": message.model_dump(mode="json"),
                        },
                        scheduled_at=now,
                        expires_at=now + timedelta(days=1),
                    )
                )
    except Exception:  # noqa: BLE001 - the badge is already awarded; push is best effort
        logger.warning(
            "badge push could not be queued",
            extra={"extra_fields": {"tenant_id": str(tenant_id)}},
            exc_info=True,
        )


async def progress(tenant_id: UUID, now: datetime | None = None) -> dict[str, Any]:
    """Level, badges and the month's gift allowance.  Read-only; awards happen on the event."""
    now = now or datetime.now(UTC)
    async with control_session_scope() as control:
        catalogue = (
            (
                await control.execute(
                    select(JalaseAchievement).order_by(
                        JalaseAchievement.sort_order, JalaseAchievement.code
                    )
                )
            )
            .scalars()
            .all()
        )
        per_hour = await platform.jalase_tokens_per_hour(control)
        streak_days = await _streak_window_days(control)
    async with session_scope(tenant_id) as session:
        values = await metrics(session, tenant_id, now, streak_days=streak_days)
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
        xp = await _xp(session, tenant_id)
    level, floor_xp, next_xp = level_for(xp)
    badges = []
    for badge in catalogue:
        row = earned.get(badge.code)
        # A badge the account already earned stays visible after the admin deactivates it.
        if not badge.active and row is None:
            continue
        badges.append(
            {
                "code": badge.code,
                "title": badge.title_fa,
                "description": badge.description_fa,
                "metric": badge.metric,
                "threshold": badge.threshold,
                "current": min(values.get(badge.metric, 0), badge.threshold),
                "reward_tokens": row.reward_tokens if row else badge.reward_tokens,
                "reward_skipped": bool(row and row.reward_tokens < badge.reward_tokens),
                "active": badge.active,
                "earned": row is not None,
                "earned_at": row.earned_at if row else None,
            }
        )
    titles = {badge.code: badge.title_fa for badge in catalogue}
    newly = [
        {
            "code": row.achievement_code,
            "title": titles.get(row.achievement_code, row.achievement_code),
            "reward_tokens": row.reward_tokens,
            "reward_skipped": False,
        }
        for row in earned.values()
        if row.notified_at is None
    ]
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


async def mark_seen(tenant_id: UUID, now: datetime | None = None) -> int:
    """Record that the app has shown the new-badge notice, so it is not repeated."""
    now = now or datetime.now(UTC)
    async with session_scope(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(JalaseEarnedAchievement).where(
                        JalaseEarnedAchievement.tenant_id == tenant_id,
                        JalaseEarnedAchievement.notified_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.notified_at = now
        return len(rows)


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
        owner_tenant = await control.get(Tenant, owner.tenant_id)
        if owner_tenant is None or owner_tenant.status != "active":
            raise ApiError(
                "invite_invalid", "کد دعوت متعلق به حسابی است که حذف یا غیرفعال شده است."
            )
        # Serialize the cap checks and the insert for one inviter, so two requests cannot both
        # pass the count and go over the monthly or per-address limit.
        await control.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"jalase-invite:{owner.tenant_id}"},
        )
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
        if await _signup_ip_is_crowded(control, invitee_tenant_id, month_start):
            raise ApiError(
                "invite_not_allowed",
                "از این شبکه پیش‌تر چند حساب با کد دعوت ساخته شده است؛ "
                "برای دریافت هدیه با پشتیبانی تماس بگیرید.",
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
        per_hour = await platform.jalase_tokens_per_hour(control)
    # Both sides are paid now, so the inviter does not have to open the progress screen.
    await settle_invites(invitee_tenant_id, now)
    await settle_invites(inviter_id, now)
    await audit_redeem(invitee_tenant_id, inviter_id, tokens)
    return {"reward_hours": round(tokens / max(1, per_hour), 1), "tokens": tokens}


async def _signup_ip_is_crowded(
    control: AsyncSession, invitee_tenant_id: UUID, since: datetime
) -> bool:
    """True when this sign-up address already produced too many rewarded invitees.

    Limits farming one reward with many phones from the same connection. A shared network
    (a family, an office) can reach the limit too, so the refusal names support as the next step.
    """
    ip = (
        await control.execute(
            select(AuditEvent.ip)
            .where(
                AuditEvent.tenant_id == invitee_tenant_id,
                AuditEvent.action == "jalase.signup",
                AuditEvent.ip.is_not(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if ip is None:
        return False
    signed_up_here = (
        select(AuditEvent.tenant_id)
        .where(AuditEvent.action == "jalase.signup", AuditEvent.ip == ip)
        .scalar_subquery()
    )
    count = (
        await control.execute(
            select(func.count())
            .select_from(JalaseInviteRedemption)
            .where(
                JalaseInviteRedemption.redeemed_at >= since,
                JalaseInviteRedemption.invitee_tenant_id.in_(signed_up_here),
            )
        )
    ).scalar_one()
    return int(count) >= INVITES_PER_IP_PER_MONTH


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
    """Pay the pending invite rewards of this account (as invitee and as inviter).

    The redemption row is locked first and the flag is checked again under that lock; the grant
    itself is idempotent by `(tenant, source, source_id)`, so a crash between the two commits
    just pays once on the next pass.
    """
    async with control_session_scope() as control:
        rows = (
            (
                await control.execute(
                    select(JalaseInviteRedemption)
                    .where(
                        (JalaseInviteRedemption.invitee_tenant_id == tenant_id)
                        | (JalaseInviteRedemption.inviter_tenant_id == tenant_id)
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            for side, done, owner, other in (
                (
                    "invitee",
                    row.invitee_granted,
                    row.invitee_tenant_id,
                    row.inviter_tenant_id,
                ),
                (
                    "inviter",
                    row.inviter_granted,
                    row.inviter_tenant_id,
                    row.invitee_tenant_id,
                ),
            ):
                if done or owner != tenant_id:
                    continue
                async with session_scope(owner) as session:
                    await token_quota.lock_tenant(session, owner)
                    await _give(
                        session,
                        owner,
                        "invite",
                        row.reward_tokens,
                        now,
                        source_id=other,
                    )
                if side == "invitee":
                    row.invitee_granted = True
                else:
                    row.inviter_granted = True


async def settle_pending_invites(now: datetime | None = None, *, limit: int = 200) -> int:
    """Safety net for a crash between the grant commit and the flag update."""
    now = now or datetime.now(UTC)
    async with control_session_scope() as control:
        pending = (
            (
                await control.execute(
                    select(JalaseInviteRedemption.invitee_tenant_id)
                    .where(
                        JalaseInviteRedemption.invitee_granted.is_(False)
                        | JalaseInviteRedemption.inviter_granted.is_(False)
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        inviters = (
            (
                await control.execute(
                    select(JalaseInviteRedemption.inviter_tenant_id)
                    .where(
                        JalaseInviteRedemption.invitee_granted.is_(False)
                        | JalaseInviteRedemption.inviter_granted.is_(False)
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    settled = 0
    for tenant_id in dict.fromkeys([*pending, *inviters]):
        await settle_invites(tenant_id, now)
        settled += 1
    return settled


async def forget_account(tenant_id: UUID) -> None:
    """Remove the invite code of a deleted account so the code cannot be redeemed again."""
    async with control_session_scope() as control:
        await control.execute(
            delete(JalaseInviteCode).where(JalaseInviteCode.tenant_id == tenant_id)
        )
