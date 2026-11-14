from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.deps import StaffSession, SuperAdminDep
from app.errors import ApiError
from app.models import SmsDelivery, SmsTemplate
from app.services import audit, demo_settings, ratelimit, sms_notify
from app.services.phone_identity import normalize_mobile
from app.services.smsir import SmsDeliveryError, send_template

router = APIRouter(prefix="/v1/admin/sms", tags=["sms"])

SAMPLE_VALUES = {
    "ORG": "سازمان نمونه",
    "AMOUNT": "1,000,000",
    "ORDER": "A1B2C3D4",
    "DAYS": "3",
    "DATE": "2026-01-01",
    "PERCENT": "80",
    "REMAINING": "120",
}


class TemplateUpdate(BaseModel):
    template_id: int | None = Field(default=None, ge=1, le=2_000_000_000)
    # provider parameter name -> canonical value key (ORG, AMOUNT, ...)
    parameters: dict[str, str] = Field(default_factory=dict, max_length=10)
    enabled: bool = False

    @field_validator("parameters")
    @classmethod
    def names_are_clean(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if not name.isascii() or not name.replace("_", "").isalnum() or len(name) > 40:
                raise ValueError("parameter names must be ASCII letters, digits or underscore")
        return value


class TestSend(BaseModel):
    mobile: str = Field(min_length=10, max_length=32)


def _view(event_key: str, row: SmsTemplate | None) -> dict[str, object]:
    event = sms_notify.EVENTS[event_key]
    return {
        "event_key": event_key,
        "title": event.title,
        "values": list(event.values),
        "template_id": row.template_id if row else None,
        "parameters": dict(row.parameters or {}) if row else {},
        "enabled": bool(row and row.enabled and row.template_id),
    }


def _event(event_key: str) -> sms_notify.SmsEvent:
    event = sms_notify.EVENTS.get(event_key)
    if event is None:
        raise ApiError("not_found", "این رویداد پیامکی وجود ندارد.")
    return event


@router.get("/templates")
async def list_templates(_: SuperAdminDep, session: StaffSession) -> list[dict[str, object]]:
    rows = {row.event_key: row for row in (await session.execute(select(SmsTemplate))).scalars()}
    return [_view(key, rows.get(key)) for key in sms_notify.EVENTS]


@router.put("/templates/{event_key}")
async def save_template(
    event_key: str, payload: TemplateUpdate, staff: SuperAdminDep, session: StaffSession
) -> dict[str, object]:
    event = _event(event_key)
    unknown = sorted(set(payload.parameters.values()) - set(event.values))
    if unknown:
        raise ApiError(
            "invalid_request",
            f"مقدارهای مجاز: {', '.join(event.values)}؛ مقدار نامعتبر: {', '.join(unknown)}",
        )
    if payload.enabled and not payload.template_id:
        raise ApiError("invalid_request", "برای فعال‌سازی، شناسه قالب sms.ir را وارد کنید.")
    row = await session.get(SmsTemplate, event_key)
    if row is None:
        row = SmsTemplate(event_key=event_key)
        session.add(row)
    row.template_id = payload.template_id
    row.parameters = payload.parameters
    row.enabled = payload.enabled
    row.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="sms_template.saved",
        payload={"event": event_key, "enabled": payload.enabled},
    )
    await session.flush()
    return _view(event_key, row)


@router.post("/templates/{event_key}/test")
async def test_template(
    event_key: str, payload: TestSend, staff: SuperAdminDep, session: StaffSession
) -> dict[str, str]:
    """Send one real SMS with sample values to an explicit recipient (costs one SMS)."""
    _event(event_key)
    await ratelimit.enforce(f"sms-template-test:{staff.id}", 5, 600)
    row = await session.get(SmsTemplate, event_key)
    if row is None or not row.template_id:
        raise ApiError("invalid_request", "ابتدا شناسه قالب این رویداد را ذخیره کنید.")
    try:
        await send_template(
            normalize_mobile(payload.mobile),
            row.template_id,
            sms_notify.build_parameters(row, dict(SAMPLE_VALUES)),
            await demo_settings.load(session),
        )
    except SmsDeliveryError as exc:
        raise ApiError(
            "sms_provider_error",
            f"ارسال پیامک انجام نشد ({exc}); کلید API و شناسه قالب را در sms.ir بررسی کنید.",
        ) from exc
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="sms_template.test_sent",
        payload={"event": event_key},
    )
    return {"status": "sent"}


@router.get("/deliveries")
async def list_deliveries(
    _: SuperAdminDep,
    session: StaffSession,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    query = select(SmsDelivery).order_by(SmsDelivery.created_at.desc()).limit(limit)
    if status:
        query = query.where(SmsDelivery.status == status)
    rows = (await session.execute(query)).scalars().all()
    return [
        {
            "id": str(row.id),
            "event_key": row.event_key,
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "mobile": f"{row.mobile[:4]}***{row.mobile[-3:]}",
            "status": row.status,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "created_at": row.created_at.isoformat(),
            "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        }
        for row in rows
    ]
