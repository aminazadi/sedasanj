from __future__ import annotations

import logging
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import control_session_scope, session_scope
from app.deps import StaffDep, StaffSession, UserDep, client_ip
from app.errors import ApiError
from app.models import Call, QuickDemoSession, RefreshToken, Tenant, User
from app.routers.phone_auth import PhoneRequest
from app.schemas import TokenPair
from app.security import create_access_token, generate_refresh_token, hash_refresh_token
from app.services import audit, commerce, demo_settings, entitlements, ratelimit
from app.services.demo_audio import normalize_upload
from app.services.demo_settings import DemoSettings
from app.services.ingest import accept_upload
from app.services.phone_identity import mobile_lock, normalize_mobile
from app.services.phone_numbers import normalize_call_number
from app.services.smsir import send_verification
from app.services.storage import get_storage

router = APIRouter(prefix="/v1", tags=["quick-demo"])
logger = logging.getLogger(__name__)


class DemoSettingsUpdate(BaseModel):
    enabled: bool | None = None
    smsir_api_key: str | None = Field(default=None, max_length=4096)
    smsir_base_url: str | None = Field(default=None, max_length=500)
    smsir_template_id: int | None = Field(default=None, ge=1)
    smsir_code_parameter: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,49}$")
    otp_ttl_seconds: int | None = Field(default=None, ge=60, le=600)
    otp_resend_seconds: int | None = Field(default=None, ge=30, le=300)
    otp_max_attempts: int | None = Field(default=None, ge=1, le=10)
    session_ttl_minutes: int | None = Field(default=None, ge=5, le=60)
    max_duration_seconds: int | None = Field(default=None, ge=10, le=600)
    max_calls_per_mobile: int | None = Field(default=None, ge=0, le=100)
    max_total_minutes: int | None = Field(default=None, ge=0, le=1000)


class SessionToken(BaseModel):
    token: str = Field(min_length=40, max_length=128)


async def limits(session: AsyncSession, settings: DemoSettings) -> int:
    if settings.max_total_minutes:
        return settings.max_total_minutes * 60
    _, version = await commerce.plan_version_by_code(session, "demo")
    return version.intro_minutes * 60


async def available_seconds(
    session: AsyncSession,
    settings: DemoSettings,
    mobile: str,
    exclude: UUID | None = None,
) -> int:
    now = datetime.now(UTC)
    rows = (
        (
            await session.execute(
                select(QuickDemoSession).where(
                    QuickDemoSession.mobile == mobile,
                    (QuickDemoSession.call_id.is_not(None)) | (QuickDemoSession.expires_at > now),
                )
            )
        )
        .scalars()
        .all()
    )
    rows = [row for row in rows if row.id != exclude]
    if settings.max_calls_per_mobile and len(rows) >= settings.max_calls_per_mobile:
        raise ApiError("quota_exceeded", "سقف تعداد تست این شماره تکمیل شده است.")
    used_ms = sum(
        row.duration_ms if row.call_id is not None else row.max_duration_seconds * 1000
        for row in rows
    )
    remaining = (await limits(session, settings)) - (used_ms + 999) // 1000
    if remaining < 1:
        raise ApiError("quota_exceeded", "اعتبار تست سریع این شماره به پایان رسیده است.")
    return min(remaining, settings.max_duration_seconds)


async def recording_session(
    session: AsyncSession, token: str, *, lock: bool = False
) -> QuickDemoSession:
    query = select(QuickDemoSession).where(QuickDemoSession.token_hash == hash_refresh_token(token))
    if lock:
        query = query.with_for_update()
    row = (
        await session.execute(query.execution_options(populate_existing=True))
    ).scalar_one_or_none()
    if row is None or row.expires_at <= datetime.now(UTC):
        raise ApiError("unauthorized", "لینک تست منقضی شده است؛ از صفحه اصلی لینک جدید بگیرید.")
    tenant = await session.get(Tenant, row.tenant_id)
    if tenant is None or tenant.status != "active":
        raise ApiError("tenant_suspended", "حساب سازمانی فعال نیست.")
    return row


@router.get("/quick-demo/config")
async def public_demo_config() -> dict[str, object]:
    async with control_session_scope() as session:
        settings = await demo_settings.load(session)
        return {
            "enabled": settings.enabled,
            "prompt_configured": bool(settings.prompt_object_key),
            "max_duration_seconds": settings.max_duration_seconds,
        }


@router.get("/admin/quick-demo/settings")
async def admin_demo_settings(staff: StaffDep, session: StaffSession) -> dict[str, object]:
    return demo_settings.public_view(await demo_settings.load(session))


@router.patch("/admin/quick-demo/settings")
async def update_demo_settings(
    payload: DemoSettingsUpdate,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, object]:
    changes = payload.model_dump(exclude_none=True)
    value = await demo_settings.save(session, changes)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="quick_demo.settings_updated",
        payload={"fields": sorted(changes)},
        ip=client_ip(request),
    )
    return demo_settings.public_view(value)


@router.post("/admin/quick-demo/prompt")
async def upload_prompt(
    staff: StaffDep,
    session: StaffSession,
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="demo-prompt-") as folder:
        target, _ = await normalize_upload(file, Path(folder), 120)
        key = f"platform/quick-demo/{uuid4()}.wav"
        await get_storage().put_path(key, target)
    value = await demo_settings.save(session, {"prompt_object_key": key})
    await audit.record(
        session, actor_type="staff", actor_id=staff.id, action="quick_demo.prompt_uploaded"
    )
    return demo_settings.public_view(value)


@router.post("/admin/quick-demo/sms-test")
async def test_sms(
    payload: PhoneRequest,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, str]:
    await ratelimit.enforce(f"demo-sms-test:{staff.id}", 3, 600)
    await send_verification(
        normalize_mobile(payload.mobile),
        f"{secrets.randbelow(1_000_000):06d}",
        await demo_settings.load(session),
    )
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="smsir.test_sent")
    return {"status": "sent"}


@router.get("/quick-demo/prompt")
async def demo_prompt() -> Response:
    async with control_session_scope() as session:
        value = await demo_settings.load(session)
        if not value.enabled or not value.prompt_object_key:
            raise ApiError("not_found", "صدای آغازین تست آماده نیست.")
        audio = await get_storage().get(value.prompt_object_key)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/quick-demo/sessions", status_code=201)
async def create_demo_session(principal: UserDep, request: Request) -> dict[str, object]:
    if principal.role not in {"org_admin", "operator"}:
        raise ApiError("forbidden", "نقش شما اجازه ارسال فایل صوتی ندارد.")
    mobile = normalize_call_number(principal.mobile_number or "")
    if not mobile.startswith("09") or len(mobile) != 11:
        raise ApiError("invalid_request", "برای تست سریع ابتدا با موبایل وارد شوید.")
    assert principal.tenant_id is not None
    await ratelimit.enforce(f"quick-demo-create:{principal.id}", 10, 600)
    async with session_scope(principal.tenant_id) as tenant_session:
        await entitlements.require_consumption(tenant_session, principal.tenant_id)
    async with control_session_scope() as session:
        value = await demo_settings.load(session)
        if not value.enabled:
            raise ApiError("forbidden", "تست سریع غیرفعال است.")
        await mobile_lock(session, mobile)
        now = datetime.now(UTC)
        # Rotating a link revokes this user's previous unused links and releases their reservations.
        await session.execute(
            update(QuickDemoSession)
            .where(
                QuickDemoSession.user_id == principal.id,
                QuickDemoSession.call_id.is_(None),
            )
            .values(expires_at=now)
        )
        max_seconds = await available_seconds(session, value, mobile)
        token = secrets.token_urlsafe(48)
        row = QuickDemoSession(
            tenant_id=principal.tenant_id,
            user_id=principal.id,
            mobile=mobile,
            token_hash=hash_refresh_token(token),
            max_duration_seconds=max_seconds,
            upload_attempt=0,
            expires_at=now + timedelta(minutes=value.session_ttl_minutes),
        )
        session.add(row)
        await session.flush()
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="quick_demo.session_created",
            payload={"session_id": str(row.id)},
            ip=client_ip(request),
        )
        return {
            "session_id": str(row.id),
            "token": token,
            "expires_at": row.expires_at.isoformat(),
            "max_duration_seconds": row.max_duration_seconds,
        }


@router.get("/quick-demo/sessions/{session_id}")
async def owner_session_status(session_id: UUID, principal: UserDep) -> dict[str, object]:
    async with control_session_scope() as session:
        row = await session.get(QuickDemoSession, session_id)
        if row is None or row.user_id != principal.id or row.tenant_id != principal.tenant_id:
            raise ApiError("not_found", "جلسه تست پیدا نشد.")
        call_deleted = False
        if row.call_id is not None:
            async with session_scope(principal.tenant_id) as tenant_session:
                call_deleted = await tenant_session.get(Call, row.call_id) is None
        return {
            "call_id": str(row.call_id) if row.call_id and not call_deleted else None,
            "call_deleted": call_deleted,
            "expires_at": row.expires_at.isoformat(),
        }


@router.post("/quick-demo/recording/status")
async def recording_status(payload: SessionToken, request: Request) -> dict[str, object]:
    await ratelimit.enforce(f"demo-status:{client_ip(request)}", 60)
    async with control_session_scope() as session:
        row = await recording_session(session, payload.token)
        value = await demo_settings.load(session)
        if not value.enabled:
            raise ApiError("forbidden", "تست سریع غیرفعال است.")
        tenant = await session.get(Tenant, row.tenant_id)
        return {
            "session_id": str(row.id),
            "user_id": str(row.user_id),
            "call_id": str(row.call_id) if row.call_id else None,
            "organization_name": tenant.name if tenant else "",
            "expires_at": row.expires_at.isoformat(),
            "completed": bool(row.call_id),
            "max_duration_seconds": min(row.max_duration_seconds, value.max_duration_seconds),
            "prompt_url": "/v1/quick-demo/prompt" if value.prompt_object_key else None,
        }


@router.post("/quick-demo/recording/login", response_model=TokenPair)
async def recording_login(payload: SessionToken, request: Request) -> TokenPair:
    await ratelimit.enforce(f"demo-login:{client_ip(request)}", 10, 600)
    async with control_session_scope() as session:
        row = await recording_session(session, payload.token, lock=True)
        if row.auth_exchanged_at is not None:
            raise ApiError("unauthorized", "این لینک قبلاً برای ورود استفاده شده است.")
        user = await session.get(User, row.user_id)
        if user is None or user.disabled_at is not None or user.tenant_id != row.tenant_id:
            raise ApiError("unauthorized", "حساب این لینک فعال نیست.")
        value = await demo_settings.load(session)
        if not value.enabled:
            raise ApiError("forbidden", "تست سریع غیرفعال است.")
        now = datetime.now(UTC)
        row.auth_exchanged_at = now
        refresh_token, refresh_hash = generate_refresh_token()
        settings = get_settings()
        session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=refresh_hash,
                expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
            )
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=user.id,
            tenant_id=user.tenant_id,
            action="auth.quick_demo_qr_login",
            ip=client_ip(request),
        )
        return TokenPair(
            access_token=create_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role),
            refresh_token=refresh_token,
            expires_in=settings.access_token_ttl_minutes * 60,
        )


@router.post("/quick-demo/recording/upload")
async def upload_recording(
    request: Request,
    token: Annotated[str, Form(min_length=40, max_length=128)],
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    await ratelimit.enforce(f"demo-upload:{client_ip(request)}", 15, 600)
    failure: ApiError | None = None
    result: dict[str, object] = {}
    async with control_session_scope() as session:
        row = await recording_session(session, token)
        await mobile_lock(session, row.mobile)
        row = await recording_session(session, token, lock=True)
        if row.call_id:
            return {"accepted": True, "replayed": True, "call_id": str(row.call_id)}
        value = await demo_settings.load(session)
        if not value.enabled:
            raise ApiError("forbidden", "تست سریع غیرفعال است.")
        remaining = await available_seconds(session, value, row.mobile, exclude=row.id)
        maximum = min(row.max_duration_seconds, remaining)
        async with session_scope(row.tenant_id) as tenant_session:
            await entitlements.require_consumption(tenant_session, row.tenant_id)
        with tempfile.TemporaryDirectory(prefix="demo-recording-") as folder:
            target, probe = await normalize_upload(file, Path(folder), maximum)
            unique_id = f"quick-demo-{row.id}-{row.upload_attempt}"
            try:
                accepted = await accept_upload(
                    tenant_id=row.tenant_id,
                    payload=target,
                    asterisk_uniqueid=unique_id,
                    caller_number=row.mobile,
                    dialed_number=row.mobile,
                    started_at=None,
                    ended_at=None,
                    direction="inbound",
                    source="browser_quick_demo",
                    external_reference=str(row.id),
                    idempotency_key=unique_id,
                    call_type="voicemail",
                    billable=False,
                    voicemail_context="quick_demo",
                    voicemail_folder="INBOX",
                    voicemail_message_id=str(row.id),
                )
                if accepted.accepted.status in {"failed_terminal", "canceled"}:
                    raise ApiError("internal", "ارسال قبلی کامل نشد؛ دوباره ارسال کنید.")
            except Exception as exc:
                row.upload_attempt += 1
                logger.warning("quick demo ingest failed", extra={"session_id": str(row.id)})
                failure = (
                    exc
                    if isinstance(exc, ApiError)
                    else ApiError("internal", "ارسال انجام نشد؛ دوباره تلاش کنید.")
                )
            else:
                row.call_id = accepted.accepted.call_id
                row.duration_ms = probe.duration_ms
                await audit.record(
                    session,
                    actor_type="user",
                    actor_id=row.user_id,
                    tenant_id=row.tenant_id,
                    action="quick_demo.recording_accepted",
                    payload={"session_id": str(row.id), "call_id": str(row.call_id)},
                )
                result = {"accepted": True, "replayed": accepted.replayed, "call_id": str(row.call_id)}
    if failure:
        raise failure
    return result
