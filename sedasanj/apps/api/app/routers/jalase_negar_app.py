"""Routes of the stand-alone Jalase-Negar app: phone sign-in and the signed-in user's data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.db import control_session_scope, session_scope
from app.deps import MeetingsKeyDep, PublicSession, client_ip
from app.errors import ApiError
from app.models import ApiKey, Meeting, Plan, PlanVersion, Subscription, Tenant, User
from app.routers import phone_auth
from app.routers.meetings import _minutes_markdown, _minutes_out, _selected_minutes
from app.security import hash_refresh_token
from app.services import audit, billing, jalase_accounts, jalase_output_types, platform, ratelimit
from app.services.ingest import ensure_monthly_plan_credit
from app.services.phone_identity import mobile_accounts, normalize_mobile

router = APIRouter(prefix="/v1/jalase-negar", tags=["jalase-negar-app"])

Platform = Literal["android", "ios", "windows", "macos", "linux", "web"]


class AuthRequest(BaseModel):
    mobile: str = Field(min_length=10, max_length=32)


class AuthVerify(BaseModel):
    otp_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class AuthComplete(BaseModel):
    verified_token: str = Field(min_length=40, max_length=256)
    display_name: str | None = Field(default=None, min_length=2, max_length=80)
    device_name: str = Field(min_length=1, max_length=80)
    platform: Platform
    app_version: str | None = Field(default=None, max_length=40)


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)


async def _require_open(session: PublicSession) -> None:
    if not await platform.jalase_standalone_enabled(session):
        raise ApiError(
            "jalase_signup_disabled",
            "ثبت‌نام مستقل جلسه‌نگار هنوز فعال نشده است؛ با کد جفت‌سازی سازمان وارد شوید.",
        )


@router.post("/auth/request", status_code=status.HTTP_201_CREATED)
async def auth_request(
    payload: AuthRequest, request: Request, session: PublicSession
) -> dict[str, object]:
    await _require_open(session)
    return await phone_auth.request_otp(session, normalize_mobile(payload.mobile), request)


@router.post("/auth/verify")
async def auth_verify(payload: AuthVerify, request: Request) -> dict[str, object]:
    result = await phone_auth.verify_otp_grant(
        phone_auth.PhoneVerify(otp_id=payload.otp_id, code=payload.code),
        request,
        product=jalase_accounts.PRODUCT,
    )
    accounts = result.get("accounts")
    return {
        "verified_token": result["verified_token"],
        "has_account": bool(accounts),
    }


def _plan_view(plan: Plan, version: PlanVersion, subscription: Subscription) -> dict[str, object]:
    return {
        "code": plan.code,
        "name": plan.name,
        "status": subscription.status,
        "monthly_minutes": version.intro_minutes,
        "period_end": None if subscription.period_end.year >= 9999 else subscription.period_end,
    }


@router.post("/auth/complete", status_code=status.HTTP_201_CREATED)
async def auth_complete(payload: AuthComplete, request: Request) -> dict[str, object]:
    await ratelimit.enforce(f"jn-complete:{hash_refresh_token(payload.verified_token)}", 10, 600)
    ip = client_ip(request)
    async with control_session_scope() as session:
        if not await platform.jalase_standalone_enabled(session):
            raise ApiError(
                "jalase_signup_disabled",
                "ثبت‌نام مستقل جلسه‌نگار هنوز فعال نشده است؛ با کد جفت‌سازی سازمان وارد شوید.",
            )
        row = await phone_auth.lock_verified_phone(
            session, payload.verified_token, error_code="unauthorized"
        )
        accounts = await mobile_accounts(session, row.mobile, product=jalase_accounts.PRODUCT)
        created = not accounts
        if accounts:
            user, tenant = accounts[0]
            if tenant.status != "active":
                raise ApiError(
                    "tenant_suspended", "حساب فعال نیست؛ با پشتیبانی جلسه‌نگار تماس بگیرید."
                )
        else:
            tenant, user = await jalase_accounts.create_personal_account(
                session, mobile=row.mobile, display_name=payload.display_name, ip=ip
            )
        row.consumed_at = datetime.now(UTC)
        secret, prefix, _key = await jalase_accounts.issue_device_key(
            session,
            user=user,
            device_name=payload.device_name,
            platform=payload.platform,
            app_version=payload.app_version,
            ip=ip,
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=user.id,
            tenant_id=tenant.id,
            action="jalase.signup" if created else "jalase.login",
            ip=ip,
        )
        return {
            "token": secret,
            "token_prefix": prefix,
            "created": created,
            "user": {
                "display_name": user.display_name,
                "mobile": jalase_accounts.mask_mobile(row.mobile),
            },
        }


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def auth_logout(principal: MeetingsKeyDep) -> None:
    """Revoke the token the app is using; it stops working immediately."""
    async with control_session_scope() as session:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.id == principal.id, ApiKey.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )


@router.get("/me")
async def me(principal: MeetingsKeyDep) -> dict[str, object]:
    assert principal.tenant_id is not None and principal.user_id is not None
    async with session_scope(None, staff=True) as session:
        user = await session.get(User, principal.user_id)
        tenant = await session.get(Tenant, principal.tenant_id)
        if user is None or tenant is None:
            raise ApiError("unauthorized", "user no longer exists")
        row = (
            await session.execute(
                select(Subscription, PlanVersion, Plan)
                .join(PlanVersion, PlanVersion.id == Subscription.plan_version_id)
                .join(Plan, Plan.id == PlanVersion.plan_id)
                .where(Subscription.tenant_id == tenant.id, Subscription.status == "active")
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
        ).first()
        # Grants this month's free allowance when the window has just rolled over.
        await ensure_monthly_plan_credit(session, tenant.id, datetime.now(UTC))
        balance = (await billing.get_balance(session, tenant.id)).seconds
    return {
        "product": tenant.product,
        "user": {
            "display_name": user.display_name,
            "mobile": jalase_accounts.mask_mobile(user.mobile_number or ""),
        },
        "plan": _plan_view(row[2], row[1], row[0]) if row else None,
        "remaining_seconds": balance,
    }


@router.patch("/me")
async def update_me(payload: ProfileUpdate, principal: MeetingsKeyDep) -> dict[str, object]:
    assert principal.user_id is not None
    async with control_session_scope() as session:
        user = await session.get(User, principal.user_id, with_for_update=True)
        if user is None:
            raise ApiError("unauthorized", "user no longer exists")
        user.display_name = payload.display_name.strip()
        return {"display_name": user.display_name}


@router.get("/meetings")
async def list_my_meetings(
    principal: MeetingsKeyDep,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, object]:
    assert principal.tenant_id is not None and principal.user_id is not None
    stmt = select(Meeting).where(
        Meeting.tenant_id == principal.tenant_id, Meeting.owner_user_id == principal.user_id
    )
    async with session_scope(principal.tenant_id) as session:
        total = int(
            (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (
                await session.execute(
                    stmt.order_by(Meeting.started_at.desc())
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            .scalars()
            .all()
        )
        return {
            "total": total,
            "page": page,
            "items": [
                {
                    "id": str(m.id),
                    "client_meeting_id": str(m.client_meeting_id),
                    "title": m.title,
                    "status": m.status,
                    "started_at": m.started_at,
                    "duration_ms": m.duration_ms,
                    "progress_pct": m.progress_pct,
                    "error_code": m.error_code,
                }
                for m in rows
            ],
        }


@router.get("/meetings/{meeting_id}/minutes")
async def my_meeting_minutes(meeting_id: UUID, principal: MeetingsKeyDep) -> dict[str, object]:
    """The selected minutes as Markdown, so the app can show and store them."""
    assert principal.tenant_id is not None and principal.user_id is not None
    async with session_scope(principal.tenant_id) as session:
        meeting = (
            await session.execute(
                select(Meeting).where(
                    Meeting.id == meeting_id,
                    Meeting.tenant_id == principal.tenant_id,
                    Meeting.owner_user_id == principal.user_id,
                )
            )
        ).scalar_one_or_none()
        if meeting is None:
            raise ApiError("meeting_not_found", "جلسه پیدا نشد.")
        minutes = await _selected_minutes(session, meeting.id)
        if minutes is None:
            return {"status": meeting.status, "version": None, "markdown": None}
        out = _minutes_out(minutes)
        return {
            "status": meeting.status,
            "version": out.version,
            "markdown": _minutes_markdown(out),
            "structured": out.structured,
        }


@router.get("/output-types")
async def output_types(principal: MeetingsKeyDep) -> dict[str, object]:
    """Conversion categories the admin published, with thumbnails and the input fields to ask."""
    assert principal.tenant_id is not None
    async with control_session_scope() as session:
        return {"items": await jalase_output_types.published_catalog(session)}
