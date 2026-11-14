"""Event notification SMS through admin-managed SMS.ir service templates.

Callers ``enqueue`` a delivery (idempotent by ``dedupe_key``, never raises); the notify worker
calls ``deliver_pending`` every minute.  Message text lives in the template on the provider's
side; only the named parameters are sent from here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import control_session_scope, session_scope
from app.errors import ApiError
from app.models import SmsDelivery, SmsTemplate, User
from app.services import demo_settings
from app.services.phone_identity import normalize_mobile
from app.services.smsir import SmsDeliveryError, send_template

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class SmsEvent:
    key: str
    title: str  # Persian label shown in admin
    values: tuple[str, ...]  # canonical value keys a template may use


EVENTS: dict[str, SmsEvent] = {
    event.key: event
    for event in (
        SmsEvent("welcome", "خوش‌آمدگویی پس از ثبت‌نام", ("ORG",)),
        SmsEvent("payment_success", "پرداخت موفق", ("ORG", "AMOUNT", "ORDER")),
        SmsEvent("renewal_due", "نزدیک‌شدن سررسید تمدید", ("ORG", "DAYS", "DATE")),
        SmsEvent("trial_ending", "نزدیک‌شدن پایان دوره آزمایشی", ("ORG", "DAYS", "DATE")),
        SmsEvent("subscription_grace", "ورود به مهلت تمدید", ("ORG", "DATE")),
        SmsEvent("subscription_expired", "پایان اشتراک", ("ORG",)),
        SmsEvent("minutes_80", "مصرف ۸۰٪ دقیقه‌های پلن", ("ORG", "PERCENT", "REMAINING")),
        SmsEvent("minutes_95", "مصرف ۹۵٪ دقیقه‌های پلن", ("ORG", "PERCENT", "REMAINING")),
        SmsEvent("minutes_exhausted", "اتمام اعتبار دقیقه", ("ORG",)),
        SmsEvent("tokens_80", "مصرف ۸۰٪ توکن هوش مصنوعی", ("ORG", "PERCENT", "REMAINING")),
        SmsEvent("tokens_95", "مصرف ۹۵٪ توکن هوش مصنوعی", ("ORG", "PERCENT", "REMAINING")),
        SmsEvent("tokens_exhausted", "اتمام توکن هوش مصنوعی", ("ORG",)),
    )
}


async def enqueue(
    event_key: str,
    mobile: str,
    params: dict[str, Any],
    dedupe_key: str,
    *,
    tenant_id: UUID | None = None,
) -> bool:
    """Queue one SMS; True when a new delivery was created.  Never raises."""
    try:
        if event_key not in EVENTS:
            raise ValueError(f"unknown sms event {event_key}")
        number = normalize_mobile(mobile)
        clean = {
            key: str(value) for key, value in params.items() if key in EVENTS[event_key].values
        }
        async with control_session_scope() as session:
            result = await session.execute(
                insert(SmsDelivery)
                .values(
                    event_key=event_key,
                    tenant_id=tenant_id,
                    mobile=number,
                    params=clean,
                    dedupe_key=dedupe_key,
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(SmsDelivery.id)
            )
            return result.first() is not None
    except (ApiError, ValueError):
        logger.warning("sms not queued", extra={"extra_fields": {"event": event_key}})
    except Exception:  # noqa: BLE001 - a notification must never break the business action
        logger.exception("sms enqueue failed", extra={"extra_fields": {"event": event_key}})
    return False


async def enqueue_for_org_admins(
    tenant_id: UUID, event_key: str, params: dict[str, Any], dedupe_key: str
) -> int:
    """Queue the SMS for every organization admin that has a mobile number."""
    try:
        async with session_scope(tenant_id) as session:
            mobiles = (
                (
                    await session.execute(
                        select(User.mobile_number).where(
                            User.tenant_id == tenant_id,
                            User.role == "org_admin",
                            User.mobile_number.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
    except Exception:  # noqa: BLE001
        logger.exception("sms recipients lookup failed")
        return 0
    created = 0
    for mobile in sorted({str(value) for value in mobiles if value}):
        if await enqueue(event_key, mobile, params, f"{dedupe_key}:{mobile}", tenant_id=tenant_id):
            created += 1
    return created


def build_parameters(template: SmsTemplate, params: dict[str, Any]) -> dict[str, str]:
    mapping = template.parameters if isinstance(template.parameters, dict) else {}
    return {str(name): str(params.get(str(source), "")) for name, source in mapping.items()}


async def deliver_pending(limit: int = 50) -> dict[str, int]:
    """Send queued SMS.  Idempotent: a row is claimed (attempts + 1) before the provider call."""
    counts = {"sent": 0, "failed": 0, "skipped": 0, "unknown": 0, "retry": 0}
    async with control_session_scope() as session:
        settings = await demo_settings.load(session)
        rows = (
            (
                await session.execute(
                    select(SmsDelivery)
                    .where(SmsDelivery.status == "pending", SmsDelivery.attempts < MAX_ATTEMPTS)
                    .order_by(SmsDelivery.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        work: list[tuple[UUID, str, str, dict[str, Any]]] = []
        for row in rows:
            row.attempts += 1
            work.append((row.id, row.event_key, row.mobile, dict(row.params or {})))
    for delivery_id, event_key, mobile, params in work:
        status, error, sent = "pending", None, None
        async with control_session_scope() as session:
            template = await session.get(SmsTemplate, event_key)
        if template is None or not template.enabled or not template.template_id:
            status, error = "skipped", "template missing or disabled"
        else:
            try:
                await send_template(
                    mobile, template.template_id, build_parameters(template, params), settings
                )
                status, sent = "sent", datetime.now(UTC)
            except SmsDeliveryError as exc:
                error = str(exc)[:200]
                if exc.unknown:
                    status = "unknown"  # may already be accepted: never retried
                elif not exc.retryable:
                    status = "failed"
        async with control_session_scope() as session:
            current = await session.get(SmsDelivery, delivery_id)
            if current is None:
                continue
            if status == "pending" and current.attempts >= MAX_ATTEMPTS:
                status = "failed"
            current.status, current.last_error, current.sent_at = status, error, sent
        counts[status if status != "pending" else "retry"] += 1
    return counts
