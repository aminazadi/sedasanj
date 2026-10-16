from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import control_session_scope
from app.deps import client_ip
from app.errors import ApiError
from app.models import PhoneOtp, RefreshToken, User
from app.schemas import TokenPair
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
    verify_totp,
)
from app.services import audit, demo_settings, ratelimit, smsir
from app.services.phone_identity import mobile_accounts, mobile_lock, normalize_mobile
from app.services.signup import create_account

router = APIRouter(prefix="/v1/auth/phone", tags=["auth"])


class PhoneRequest(BaseModel):
    mobile: str = Field(min_length=10, max_length=32)


class PhoneVerify(BaseModel):
    otp_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class PhoneComplete(BaseModel):
    verified_token: str = Field(min_length=40, max_length=256)
    organization_name: str | None = Field(default=None, min_length=2, max_length=200)
    user_id: UUID | None = None
    totp_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


async def issue_tokens(session: AsyncSession, user: User) -> TokenPair:
    settings = get_settings()
    refresh, hashed = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hashed,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    return TokenPair(
        access_token=create_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role),
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/request", status_code=201)
async def request_phone_otp(payload: PhoneRequest, request: Request) -> dict[str, object]:
    mobile = normalize_mobile(payload.mobile)
    await ratelimit.enforce(f"phone-otp-ip:{client_ip(request)}", 10, 3600)
    await ratelimit.enforce(f"phone-otp-mobile:{mobile}", 5, 3600)
    async with control_session_scope() as session:
        settings = await demo_settings.load(session)
        await mobile_lock(session, mobile)
        now = datetime.now(UTC)
        recent = (
            await session.execute(
                select(PhoneOtp)
                .where(PhoneOtp.mobile == mobile)
                .order_by(PhoneOtp.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent and recent.created_at > now - timedelta(seconds=settings.otp_resend_seconds):
            raise ApiError("rate_limited", "برای ارسال دوباره کد کمی صبر کنید.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        await smsir.send_verification(mobile, code, settings)
        await session.execute(
            update(PhoneOtp)
            .where(
                PhoneOtp.mobile == mobile,
                PhoneOtp.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        row = PhoneOtp(
            mobile=mobile,
            code_hash=hash_password(code),
            attempts=0,
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        )
        session.add(row)
        await session.flush()
        await audit.record(
            session,
            actor_type="public",
            action="phone.otp_requested",
            payload={"otp_id": str(row.id)},
            ip=client_ip(request),
        )
        return {
            "otp_id": str(row.id),
            "expires_in": settings.otp_ttl_seconds,
            "resend_after": settings.otp_resend_seconds,
        }


@router.post("/verify")
async def verify_phone_otp(payload: PhoneVerify, request: Request) -> dict[str, object]:
    await ratelimit.enforce(f"phone-verify:{client_ip(request)}", 30, 600)
    failure: ApiError | None = None
    result: dict[str, object] = {}
    # Failed attempts must commit before an error response is raised.
    async with control_session_scope() as session:
        settings = await demo_settings.load(session)
        row = await session.get(PhoneOtp, payload.otp_id, with_for_update=True)
        now = datetime.now(UTC)
        if (
            row is None
            or row.expires_at <= now
            or row.consumed_at is not None
            or row.verified_at is not None
            or row.attempts >= settings.otp_max_attempts
        ):
            failure = ApiError("unauthorized", "کد منقضی یا مصرف شده است؛ کد جدید بگیرید.")
        elif not verify_password(row.code_hash, payload.code):
            row.attempts += 1
            failure = ApiError("unauthorized", "کد تأیید نادرست است.")
        else:
            grant = secrets.token_urlsafe(48)
            row.verified_at = now
            row.grant_hash = hash_refresh_token(grant)
            row.grant_expires_at = now + timedelta(minutes=10)
            accounts = await mobile_accounts(session, row.mobile)
            result = {
                "verified_token": grant,
                "accounts": [
                    {
                        "user_id": str(user.id),
                        "organization_name": tenant.name,
                        "requires_totp": bool(user.totp_secret),
                        "active": tenant.status == "active",
                    }
                    for user, tenant in accounts
                ],
            }
            await audit.record(
                session,
                actor_type="public",
                action="phone.otp_verified",
                payload={"otp_id": str(row.id)},
                ip=client_ip(request),
            )
    if failure:
        raise failure
    return result


@router.post("/complete", response_model=TokenPair)
async def complete_phone_login(payload: PhoneComplete, request: Request) -> TokenPair:
    await ratelimit.enforce(f"phone-complete:{hash_refresh_token(payload.verified_token)}", 10, 600)
    async with control_session_scope() as session:
        grant_query = select(PhoneOtp).where(
            PhoneOtp.grant_hash == hash_refresh_token(payload.verified_token)
        )
        candidate = (await session.execute(grant_query)).scalar_one_or_none()
        if candidate is None:
            raise ApiError("unauthorized", "تأیید شماره منقضی شده است؛ دوباره کد بگیرید.")
        await mobile_lock(session, candidate.mobile)
        row = (
            await session.execute(
                grant_query.with_for_update().execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if (
            row is None
            or row.verified_at is None
            or row.consumed_at is not None
            or row.grant_expires_at is None
            or row.grant_expires_at <= now
        ):
            raise ApiError("unauthorized", "تأیید شماره منقضی شده است؛ دوباره کد بگیرید.")
        accounts = await mobile_accounts(session, row.mobile)
        if accounts:
            chosen = next(
                ((user, tenant) for user, tenant in accounts if user.id == payload.user_id), None
            )
            if chosen is None and len(accounts) == 1 and payload.user_id is None:
                chosen = accounts[0]
            if chosen is None:
                raise ApiError("invalid_request", "سازمان خود را انتخاب کنید.")
            user, tenant = chosen
            if tenant.status != "active":
                raise ApiError(
                    "tenant_suspended", "حساب سازمانی فعال نیست؛ با پشتیبانی تماس بگیرید."
                )
            if user.totp_secret and not verify_totp(user.totp_secret, payload.totp_code):
                raise ApiError("unauthorized", "کد ورود دومرحله‌ای را درست وارد کنید.")
        else:
            if not payload.organization_name or len(payload.organization_name.strip()) < 2:
                raise ApiError("invalid_request", "نام سازمان را وارد کنید.")
            settings = await demo_settings.load(session)
            if not settings.enabled:
                raise ApiError("forbidden", "ایجاد دموی سریع در حال حاضر فعال نیست.")
            _, user = await create_account(
                session,
                mobile=row.mobile,
                email=f"phone-{uuid4().hex}@accounts.sedasanj.ir",
                organization_name=payload.organization_name.strip(),
                manager_name=payload.organization_name.strip(),
                password=secrets.token_urlsafe(48),
                plan_code="demo",
                ip=client_ip(request),
            )
        row.consumed_at = now
        pair = await issue_tokens(session, user)
        await audit.record(
            session,
            actor_type="user",
            actor_id=user.id,
            tenant_id=user.tenant_id,
            action="auth.phone_login",
            ip=client_ip(request),
        )
        return pair
