"""Staff view of every user across products, with filters, export and bulk actions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.deps import StaffDep, StaffSession, SuperAdminDep, client_ip
from app.errors import ApiError
from app.models import Plan, PlanVersion, SmsTemplate, Subscription, Tenant, User
from app.routers import admin
from app.services import assistant_export_renderers, audit, billing, jalase_accounts, sms_notify
from app.services.call_export import to_jalali

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin/users", tags=["admin"])

BULK_MAX = 500
EXPORT_MAX = 50_000
PRODUCTS = ("sedasanj", "jalase_negar")

EXPORT_COLUMNS = {
    "name": "نام",
    "mobile": "موبایل",
    "product": "محصول",
    "channel": "کانال ثبت‌نام",
    "plan": "پلن",
    "subscription": "وضعیت اشتراک",
    "tenant": "سازمان",
    "tenant_status": "وضعیت حساب",
    "created": "تاریخ عضویت",
}
PRODUCT_LABELS = {"sedasanj": "صداسنج", "jalase_negar": "جلسه‌نگار"}


class UserFilters(BaseModel):
    product: Literal["sedasanj", "jalase_negar"] | None = None
    signup_channel: str | None = Field(default=None, max_length=32)
    plan_code: str | None = Field(default=None, max_length=32)
    subscription_status: str | None = Field(default=None, max_length=32)
    created_from: datetime | None = None
    created_to: datetime | None = None
    q: str | None = Field(default=None, max_length=100)


def filters_from_query(
    product: Annotated[Literal["sedasanj", "jalase_negar"] | None, Query()] = None,
    signup_channel: Annotated[str | None, Query(max_length=32)] = None,
    plan_code: Annotated[str | None, Query(max_length=32)] = None,
    subscription_status: Annotated[str | None, Query(max_length=32)] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> UserFilters:
    return UserFilters(
        product=product,
        signup_channel=signup_channel,
        plan_code=plan_code,
        subscription_status=subscription_status,
        created_from=created_from,
        created_to=created_to,
        q=q,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def users_query(filters: UserFilters) -> Select[Any]:
    """Users joined with their tenant and the tenant's newest subscription and plan."""
    newest = (
        select(
            Subscription.tenant_id.label("tenant_id"),
            Subscription.status.label("status"),
            Subscription.plan_version_id.label("plan_version_id"),
            func.row_number()
            .over(partition_by=Subscription.tenant_id, order_by=Subscription.created_at.desc())
            .label("rn"),
        )
    ).subquery()
    stmt = (
        select(
            User,
            Tenant,
            Plan.code.label("plan_code"),
            Plan.name.label("plan_name"),
            newest.c.status.label("subscription_status"),
        )
        .join(Tenant, Tenant.id == User.tenant_id)
        .outerjoin(newest, (newest.c.tenant_id == Tenant.id) & (newest.c.rn == 1))
        .outerjoin(PlanVersion, PlanVersion.id == newest.c.plan_version_id)
        .outerjoin(Plan, Plan.id == PlanVersion.plan_id)
        .where(Tenant.status != "deleted")
    )
    if filters.product:
        stmt = stmt.where(Tenant.product == filters.product)
    if filters.signup_channel:
        stmt = stmt.where(User.signup_channel == filters.signup_channel)
    if filters.plan_code:
        stmt = stmt.where(Plan.code == filters.plan_code)
    if filters.subscription_status:
        stmt = stmt.where(newest.c.status == filters.subscription_status)
    if filters.created_from:
        stmt = stmt.where(User.created_at >= filters.created_from)
    if filters.created_to:
        stmt = stmt.where(User.created_at <= filters.created_to)
    if filters.q and filters.q.strip():
        like = f"%{_escape_like(filters.q.strip())}%"
        stmt = stmt.where(
            or_(
                User.mobile_number.ilike(like, escape="\\"),
                User.display_name.ilike(like, escape="\\"),
                User.email.ilike(like, escape="\\"),
                Tenant.name.ilike(like, escape="\\"),
            )
        )
    return stmt


def _row_out(row: Any) -> dict[str, Any]:
    user, tenant = row.User, row.Tenant
    return {
        "id": str(user.id),
        "tenant_id": str(tenant.id),
        "name": user.display_name,
        "mobile": user.mobile_number,
        "email": user.email,
        "role": user.role,
        "product": tenant.product,
        "signup_channel": user.signup_channel or tenant.signup_channel,
        "tenant_name": tenant.name,
        "tenant_status": tenant.status,
        "plan_code": row.plan_code,
        "plan_name": row.plan_name,
        "subscription_status": row.subscription_status,
        "created_at": user.created_at,
    }


@router.get("")
async def list_users(
    staff: StaffDep,
    session: StaffSession,
    filters: Annotated[UserFilters, Depends(filters_from_query)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> dict[str, Any]:
    stmt = users_query(filters)
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = (
        await session.execute(stmt.order_by(User.created_at.desc()).offset(offset).limit(limit))
    ).all()
    return {
        "items": [_row_out(row) for row in rows],
        "total": total,
        "next_cursor": str(offset + len(rows)) if offset + len(rows) < total else None,
    }


@router.get("/export")
async def export_users(
    request: Request,
    staff: StaffDep,
    session: StaffSession,
    filters: Annotated[UserFilters, Depends(filters_from_query)],
    export_format: Annotated[Literal["csv", "xlsx"], Query(alias="format")] = "csv",
) -> Response:
    """The filtered list as CSV or Excel; cells are neutralised against formula injection."""
    stmt = users_query(filters).order_by(User.created_at.desc()).limit(EXPORT_MAX + 1)
    rows = (await session.execute(stmt)).all()
    if len(rows) > EXPORT_MAX:
        raise ApiError(
            "bulk_action_too_large",
            f"بیش از {EXPORT_MAX} ردیف است؛ فیلتر را محدودتر کنید.",
        )
    table = []
    for row in rows:
        out = _row_out(row)
        table.append(
            {
                "name": out["name"] or "",
                "mobile": out["mobile"] or "",
                "product": PRODUCT_LABELS.get(out["product"], out["product"]),
                "channel": out["signup_channel"] or "",
                "plan": out["plan_name"] or "",
                "subscription": out["subscription_status"] or "",
                "tenant": out["tenant_name"],
                "tenant_status": out["tenant_status"],
                "created": to_jalali(out["created_at"]),
            }
        )
    body = assistant_export_renderers.render(
        export_format, EXPORT_COLUMNS, table, sheet_title="کاربران"
    )
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="users.export",
        payload={"count": len(rows), "format": export_format, **_filter_summary(filters)},
        ip=client_ip(request),
    )
    return Response(
        body,
        media_type=assistant_export_renderers.MEDIA_TYPES[export_format],
        headers={"Content-Disposition": f'attachment; filename="users.{export_format}"'},
    )


def _filter_summary(filters: UserFilters) -> dict[str, Any]:
    """Filter values for the audit log; the free-text search may hold a phone number, so skip it."""
    return {
        "filters": {
            key: str(value)
            for key, value in filters.model_dump(exclude={"q"}, exclude_none=True).items()
        },
        "searched": bool(filters.q),
    }


class BulkRequest(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["suspend", "unsuspend", "grant_credit", "sms"]
    user_ids: list[UUID] | None = Field(default=None, max_length=BULK_MAX)
    filters: UserFilters = Field(default_factory=UserFilters)
    dry_run: bool = True
    minutes: int | None = Field(default=None, ge=1, le=100_000)
    message: str | None = Field(default=None, min_length=1, max_length=300)
    note: str = Field(default="", max_length=300)


async def _bulk_targets(session: AsyncSession, payload: BulkRequest) -> list[Any]:
    # Bulk actions touch Jalase-Negar accounts only; SedaSanj organisations keep their own pages.
    filters = payload.filters.model_copy(update={"product": jalase_accounts.PRODUCT})
    stmt = users_query(filters)
    if payload.user_ids is not None:
        stmt = stmt.where(User.id.in_(payload.user_ids))
    rows = (await session.execute(stmt.order_by(User.created_at).limit(BULK_MAX + 1))).all()
    if len(rows) > BULK_MAX:
        raise ApiError(
            "bulk_action_too_large",
            f"حداکثر {BULK_MAX} کاربر در هر اجرا؛ فیلتر را محدودتر کنید.",
        )
    return list(rows)


@router.post("/bulk")
async def bulk_action(
    payload: BulkRequest, request: Request, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    """Preview (`dry_run`, the default) or run an action on up to 500 Jalase-Negar users."""
    if payload.action == "grant_credit" and payload.minutes is None:
        raise ApiError("invalid_request", "تعداد دقیقه را وارد کنید.")
    if payload.action == "sms":
        if not payload.message:
            raise ApiError("invalid_request", "متن پیام را وارد کنید.")
        template = await session.get(SmsTemplate, "jalase_broadcast")
        if template is None or not template.enabled or not template.template_id:
            raise ApiError(
                "sms_template_missing",
                "قالب «پیام گروهی به کاربران جلسه‌نگار» در تنظیمات پیامک فعال نیست.",
            )
    rows = await _bulk_targets(session, payload)
    if payload.dry_run:
        return {"dry_run": True, "count": len(rows), "action": payload.action}
    run_id = uuid4().hex
    done = 0
    for row in rows:
        user, tenant = row.User, row.Tenant
        if payload.action in ("suspend", "unsuspend"):
            target = "suspended" if payload.action == "suspend" else "active"
            if tenant.status != target:
                await admin._set_tenant_status(tenant.id, target, request, staff, session)
                done += 1
        elif payload.action == "grant_credit":
            assert payload.minutes is not None
            async with session_scope(tenant.id) as tenant_session:
                projection = await tenant_session.get(Tenant, tenant.id)
                if projection is None:
                    continue
                await billing.topup(
                    tenant_session,
                    tenant=projection,
                    minutes=payload.minutes,
                    idempotency_key=f"bulk-credit:{run_id}:{tenant.id}",
                )
            done += 1
        elif payload.action == "sms" and user.mobile_number:
            queued = await sms_notify.enqueue(
                "jalase_broadcast",
                user.mobile_number,
                {"NAME": user.display_name or "", "MESSAGE": payload.message or ""},
                f"bulk-sms:{run_id}:{user.id}",
                tenant_id=tenant.id,
            )
            done += int(queued)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action=f"users.bulk.{payload.action}",
        payload={
            "run_id": run_id,
            "targets": len(rows),
            "done": done,
            "minutes": payload.minutes,
            "note": payload.note,
            **_filter_summary(payload.filters),
        },
        ip=client_ip(request),
    )
    return {"dry_run": False, "count": len(rows), "done": done, "run_id": run_id}
