"""Subscription notices (renewal due, trial ending, grace, expiry), each sent once per period."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import routable_tenant_ids, session_scope
from app.models import Invoice, NotificationLog, Subscription, Tenant, User
from app.services import subscription_state
from app.services.commerce_settings import get_commerce_settings

logger = logging.getLogger(__name__)

Send = Callable[[str, str, str], Awaitable[None]]
MAX_ATTEMPTS = 3
RENEWAL_NOTICE_DAYS = (7, 1)
TRIAL_NOTICE_DAYS = 2
EXPIRED_NOTICE_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class Notice:
    subscription_id: UUID
    kind: str
    period_key: str
    subject: str
    body: str


def _day(value: datetime) -> str:
    return f"{value:%Y-%m-%d}"


def _compose(kind: str, tenant_name: str, period_end: datetime, link: str) -> tuple[str, str]:
    end = _day(period_end)
    if kind == "renewal_due":
        return (
            "اشتراک صداسنج شما به‌زودی تمام می‌شود",
            f"سازمان {tenant_name}: اشتراک تا {end} معتبر است. برای جلوگیری از قطع سرویس، "
            f"سفارش تمدید را از بخش حساب پرداخت کنید: {link}",
        )
    if kind == "trial_ending":
        return (
            "دوره آزمایشی صداسنج رو به پایان است",
            f"سازمان {tenant_name}: دوره آزمایشی تا {end} ادامه دارد. برای ادامه، یک پلن "
            f"انتخاب کنید: {link}",
        )
    if kind == "grace_started":
        return (
            "اشتراک صداسنج منقضی شده و مهلت تمدید فعال است",
            f"سازمان {tenant_name}: اشتراک در {end} تمام شد و سرویس فعلاً در مهلت تمدید کار "
            f"می‌کند. برای جلوگیری از قطع، همین حالا تمدید کنید: {link}",
        )
    return (
        "اشتراک صداسنج پایان یافته است",
        f"سازمان {tenant_name}: اشتراک در {end} تمام شد و پردازش جدید متوقف است. برای "
        f"فعال‌سازی دوباره، پلن را تمدید کنید: {link}",
    )


async def due_notices(session: AsyncSession, tenant_id: UUID, now: datetime) -> list[Notice]:
    """Notices that apply to the tenant's subscriptions right now (not yet filtered by the log)."""
    days = (await get_commerce_settings(session)).grace_days
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        return []
    link = f"{get_settings().public_app_url.rstrip('/')}/account"
    has_paid = (
        await session.execute(select(Invoice.id).where(Invoice.tenant_id == tenant_id).limit(1))
    ).scalar_one_or_none() is not None
    subscriptions = (
        (
            await session.execute(
                select(Subscription).where(
                    Subscription.tenant_id == tenant_id,
                    Subscription.status.in_(("active", "trialing", "expired")),
                    Subscription.period_end > now - EXPIRED_NOTICE_WINDOW,
                    Subscription.period_end <= now + timedelta(days=max(RENEWAL_NOTICE_DAYS)),
                )
            )
        )
        .scalars()
        .all()
    )
    notices: list[Notice] = []

    def add(subscription: Subscription, kind: str, key: str) -> None:
        subject, body = _compose(kind, tenant.name, subscription.period_end, link)
        notices.append(Notice(subscription.id, kind, key, subject, body))

    for subscription in subscriptions:
        left = subscription.period_end - now
        effective = subscription_state.effective_status(subscription, now, days)
        stamp = _day(subscription.period_end)
        if subscription.status == "active" and not subscription.cancel_at_period_end:
            for window in RENEWAL_NOTICE_DAYS:
                if timedelta(0) < left <= timedelta(days=window):
                    add(subscription, "renewal_due", f"{stamp}:{window}")
        if subscription.status == "trialing" and timedelta(0) < left <= timedelta(
            days=TRIAL_NOTICE_DAYS
        ):
            add(subscription, "trial_ending", stamp)
        if effective == "grace":
            add(subscription, "grace_started", stamp)
        if effective == "expired" and (has_paid or subscription.billing_period == "trial"):
            add(subscription, "subscription_expired", stamp)
    return notices


async def _recipients(session: AsyncSession, tenant_id: UUID) -> list[str]:
    rows = await session.execute(
        select(User.email).where(User.tenant_id == tenant_id, User.role == "org_admin")
    )
    return [str(email) for email in rows.scalars() if email]


async def _claim(session: AsyncSession, tenant_id: UUID, notice: Notice) -> NotificationLog | None:
    row = (
        await session.execute(
            select(NotificationLog)
            .where(
                NotificationLog.subscription_id == notice.subscription_id,
                NotificationLog.kind == notice.kind,
                NotificationLog.period_key == notice.period_key,
                NotificationLog.channel == "email",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = NotificationLog(
            tenant_id=tenant_id,
            subscription_id=notice.subscription_id,
            kind=notice.kind,
            period_key=notice.period_key,
        )
        session.add(row)
    elif row.status == "sent" or row.attempts >= MAX_ATTEMPTS:
        return None
    row.attempts = (row.attempts or 0) + 1
    await session.flush()
    return row


async def send_tenant_notices(tenant_id: UUID, now: datetime, send: Send) -> int:
    """Send every unsent notice of one tenant; return how many were delivered to the mail relay."""
    async with session_scope(tenant_id) as session:
        notices = await due_notices(session, tenant_id, now)
        recipients = await _recipients(session, tenant_id) if notices else []
    delivered = 0
    for notice in notices:
        async with session_scope(tenant_id) as session:
            claim = await _claim(session, tenant_id, notice)
            claim_id = claim.id if claim else None
        if claim_id is None:
            continue
        error: str | None = None
        if not recipients:
            error = "no organization admin email"
        else:
            try:
                for address in recipients:
                    await send(address, notice.subject, notice.body)
            except Exception as exc:  # noqa: BLE001 - one bad send must not stop the sweep
                error = type(exc).__name__
        async with session_scope(tenant_id) as session:
            row = await session.get(NotificationLog, claim_id)
            if row is None:
                continue
            if error is None:
                row.status, row.sent_at, row.last_error = "sent", datetime.now(UTC), None
                delivered += 1
            else:
                row.status, row.last_error = "failed", error
    return delivered


async def send_due_notices(send: Send, now: datetime | None = None) -> int:
    """Cron entry: one tenant failing never blocks the others."""
    moment = now or datetime.now(UTC)
    total = 0
    for tenant_id in await routable_tenant_ids():
        try:
            total += await send_tenant_notices(tenant_id, moment, send)
        except Exception:  # noqa: BLE001
            logger.exception(
                "subscription notices failed", extra={"extra_fields": {"tenant_id": str(tenant_id)}}
            )
    return total
