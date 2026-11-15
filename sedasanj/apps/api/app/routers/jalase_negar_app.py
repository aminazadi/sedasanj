"""Routes of the stand-alone Jalase-Negar app: phone sign-in and the signed-in user's data."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import control_session_scope, session_scope
from app.deps import MeetingsKeyDep, PublicSession, client_ip
from app.errors import ApiError
from app.models import (
    ApiKey,
    JalaseOutputType,
    Meeting,
    MeetingDocument,
    MeetingDocumentVersion,
    MeetingSegment,
    Order,
    Plan,
    PlanVersion,
    Subscription,
    Tenant,
    TokenPackage,
    User,
)
from app.routers import phone_auth, token_packages
from app.routers.meetings import _minutes_markdown, _minutes_out, _selected_minutes
from app.schemas import MeetingPairIn
from app.security import hash_refresh_token
from app.services import (
    audit,
    billing,
    commerce,
    document_docx,
    document_pdf,
    jalase_accounts,
    jalase_billing,
    jalase_links,
    jalase_output_types,
    jalase_rewards,
    meeting_documents,
    payments,
    platform,
    ratelimit,
)
from app.services.ingest import ensure_monthly_plan_credit
from app.services.phone_identity import mobile_accounts, normalize_mobile
from app.services.queue import JOB_MEETING_DOCUMENT, QUEUE_MEETING, get_queue

logger = logging.getLogger(__name__)
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
        usage = await jalase_billing.usage(session, tenant.id)
    return {
        "product": tenant.product,
        "user": {
            "display_name": user.display_name,
            "mobile": jalase_accounts.mask_mobile(user.mobile_number or ""),
        },
        "plan": _plan_view(row[2], row[1], row[0]) if row else None,
        "remaining_seconds": balance,
        "usage": usage,
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


class DocumentItem(BaseModel):
    output_type: str = Field(min_length=2, max_length=40)
    input_values: dict[str, str] = Field(default_factory=dict)
    note: str = Field(default="", max_length=500)


class DocumentsCreate(BaseModel):
    items: list[DocumentItem] = Field(min_length=1, max_length=5)


class DocumentRegenerate(BaseModel):
    input_values: dict[str, str] | None = None
    note: str | None = Field(default=None, max_length=500)


class DocumentEdit(BaseModel):
    markdown: str = Field(min_length=1, max_length=200_000)


MAX_DOCUMENT_VERSIONS = 50


def _personal(principal: MeetingsKeyDep) -> tuple[UUID, UUID]:
    if principal.tenant_id is None or principal.user_id is None:
        raise ApiError(
            "forbidden",
            "این بخش فقط برای حساب شخصی جلسه‌نگار است؛ با شمارهٔ موبایل وارد شوید.",
        )
    return principal.tenant_id, principal.user_id


def _document_out(document: MeetingDocument, selected: int | None = None) -> dict[str, object]:
    return {
        "id": str(document.id),
        "meeting_id": str(document.meeting_id),
        "output_type": document.output_type_code,
        "output_type_version": document.output_type_version,
        "status": document.status,
        "progress_pct": document.progress_pct,
        "error_code": document.error_code,
        "input_values": document.input_values,
        "note": document.user_note,
        "selected_version": selected,
        "updated_at": document.updated_at,
    }


async def _enqueue_document(tenant_id: UUID, document_id: UUID) -> None:
    # A lost job is picked up by the worker's reconciler a few minutes later.
    try:
        await get_queue().enqueue(
            QUEUE_MEETING,
            JOB_MEETING_DOCUMENT,
            {"tenant_id": str(tenant_id), "document_id": str(document_id)},
            job_id=f"meeting-doc:{document_id}:{uuid4().hex[:8]}",
        )
    except Exception:  # noqa: BLE001 - never fail the request over the queue
        logger.warning("meeting document enqueue failed", exc_info=True)


async def _owned_meeting(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, meeting_id: UUID
) -> Meeting:
    meeting = (
        await session.execute(
            select(Meeting).where(
                Meeting.id == meeting_id,
                Meeting.tenant_id == tenant_id,
                Meeting.owner_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise ApiError("meeting_not_found", "جلسه پیدا نشد.")
    return meeting


async def _owned_document(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, document_id: UUID, *, lock: bool = False
) -> MeetingDocument:
    statement = (
        select(MeetingDocument)
        .join(Meeting, Meeting.id == MeetingDocument.meeting_id)
        .where(
            MeetingDocument.id == document_id,
            MeetingDocument.tenant_id == tenant_id,
            Meeting.owner_user_id == user_id,
        )
    )
    if lock:
        statement = statement.with_for_update(of=MeetingDocument)
    document = (await session.execute(statement)).scalar_one_or_none()
    if document is None:
        raise ApiError("document_not_found", "سند پیدا نشد.")
    return document


async def _selected_version(
    session: AsyncSession, document_id: UUID
) -> MeetingDocumentVersion | None:
    return (
        await session.execute(
            select(MeetingDocumentVersion).where(
                MeetingDocumentVersion.document_id == document_id,
                MeetingDocumentVersion.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()


@router.post("/meetings/{meeting_id}/documents", status_code=status.HTTP_201_CREATED)
async def create_documents(
    meeting_id: UUID, payload: DocumentsCreate, principal: MeetingsKeyDep
) -> dict[str, object]:
    """Start one document per chosen output type; asking again for a type returns its document."""
    tenant_id, user_id = _personal(principal)
    await ratelimit.enforce(f"jn-doc:{user_id}", 30, 3600)
    codes = [item.output_type for item in payload.items]
    if len(set(codes)) != len(codes):
        raise ApiError("document_input_invalid", "یک دسته را فقط یک بار انتخاب کنید.")
    prepared: list[tuple[DocumentItem, int, dict[str, str]]] = []
    async with control_session_scope() as control:
        for item in payload.items:
            output_type, version = await jalase_output_types.published_version(
                control, item.output_type
            )
            if output_type.builtin:
                raise ApiError(
                    "document_input_invalid",
                    "صورت‌جلسه به‌صورت خودکار ساخته می‌شود؛ آن را در فهرست انتخاب نکنید.",
                )
            values = jalase_output_types.validate_input_values(
                version.input_fields, item.input_values
            )
            prepared.append((item, version.version, values))
    queued: list[UUID] = []
    async with session_scope(tenant_id) as session:
        await _owned_meeting(session, tenant_id, user_id, meeting_id)
        has_text = (
            await session.execute(
                select(MeetingSegment.id).where(MeetingSegment.meeting_id == meeting_id).limit(1)
            )
        ).first()
        if has_text is None:
            raise ApiError(
                "meeting_transcript_missing",
                "متنی برای این جلسه به سرور نرسیده است؛ در اپ «ارسال متن این جلسه» را بزنید.",
            )
        out: list[dict[str, object]] = []
        for item, version_number, values in prepared:
            document = (
                await session.execute(
                    select(MeetingDocument)
                    .where(
                        MeetingDocument.meeting_id == meeting_id,
                        MeetingDocument.output_type_code == item.output_type,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if document is None:
                document = MeetingDocument(
                    tenant_id=tenant_id,
                    meeting_id=meeting_id,
                    output_type_code=item.output_type,
                    output_type_version=version_number,
                    input_values=values,
                    user_note=item.note.strip(),
                )
                session.add(document)
                await session.flush()
                queued.append(document.id)
            elif document.status == "failed":
                document.output_type_version = version_number
                document.input_values = values
                document.user_note = item.note.strip()
                await meeting_documents.reopen(session, document)
                queued.append(document.id)
            selected = await _selected_version(session, document.id)
            out.append(_document_out(document, selected.version if selected else None))
    for document_id in queued:
        await _enqueue_document(tenant_id, document_id)
    return {"items": out}


@router.get("/meetings/{meeting_id}/documents")
async def list_documents(meeting_id: UUID, principal: MeetingsKeyDep) -> dict[str, object]:
    tenant_id, user_id = _personal(principal)
    async with session_scope(tenant_id) as session:
        await _owned_meeting(session, tenant_id, user_id, meeting_id)
        rows = (
            (
                await session.execute(
                    select(MeetingDocument)
                    .where(MeetingDocument.meeting_id == meeting_id)
                    .order_by(MeetingDocument.created_at)
                )
            )
            .scalars()
            .all()
        )
        items = []
        for document in rows:
            selected = await _selected_version(session, document.id)
            items.append(_document_out(document, selected.version if selected else None))
        return {"items": items}


@router.get("/documents/{document_id}")
async def get_document(document_id: UUID, principal: MeetingsKeyDep) -> dict[str, object]:
    tenant_id, user_id = _personal(principal)
    async with session_scope(tenant_id) as session:
        document = await _owned_document(session, tenant_id, user_id, document_id)
        versions = (
            (
                await session.execute(
                    select(MeetingDocumentVersion)
                    .where(MeetingDocumentVersion.document_id == document_id)
                    .order_by(MeetingDocumentVersion.version.desc())
                )
            )
            .scalars()
            .all()
        )
        chosen = next((v for v in versions if v.is_selected), None)
        return {
            **_document_out(document, chosen.version if chosen else None),
            "markdown": chosen.markdown if chosen else None,
            "versions": [
                {
                    "version": v.version,
                    "source": v.source,
                    "selected": v.is_selected,
                    "created_at": v.created_at,
                }
                for v in versions
            ],
        }


async def _new_version_count(session: AsyncSession, document_id: UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.coalesce(func.max(MeetingDocumentVersion.version), 0)).where(
                    MeetingDocumentVersion.document_id == document_id
                )
            )
        ).scalar_one()
    )


@router.patch("/documents/{document_id}")
async def edit_document(
    document_id: UUID, payload: DocumentEdit, principal: MeetingsKeyDep
) -> dict[str, object]:
    """Save the user's edit as a new selected version; earlier versions stay."""
    tenant_id, user_id = _personal(principal)
    async with session_scope(tenant_id) as session:
        document = await _owned_document(session, tenant_id, user_id, document_id, lock=True)
        if document.status != "done":
            raise ApiError(
                "document_input_invalid", "سند هنوز آماده نیست؛ پس از ساخت آن را ویرایش کنید."
            )
        latest = await _new_version_count(session, document_id)
        if latest >= MAX_DOCUMENT_VERSIONS:
            raise ApiError(
                "document_input_invalid",
                "تعداد نسخه‌های این سند به سقف رسیده است؛ سند را دوباره بسازید.",
            )
        await session.execute(
            update(MeetingDocumentVersion)
            .where(MeetingDocumentVersion.document_id == document_id)
            .values(is_selected=False)
        )
        session.add(
            MeetingDocumentVersion(
                tenant_id=tenant_id,
                document_id=document_id,
                version=latest + 1,
                markdown=payload.markdown.strip() + "\n",
                source="user_edit",
                is_selected=True,
            )
        )
        document.updated_at = datetime.now(UTC)
        return {"version": latest + 1}


@router.post("/documents/{document_id}/versions/{version}/select")
async def select_document_version(
    document_id: UUID, version: int, principal: MeetingsKeyDep
) -> dict[str, object]:
    tenant_id, user_id = _personal(principal)
    async with session_scope(tenant_id) as session:
        await _owned_document(session, tenant_id, user_id, document_id, lock=True)
        target = await session.get(MeetingDocumentVersion, (document_id, version))
        if target is None:
            raise ApiError("document_not_found", "این نسخه پیدا نشد.")
        await session.execute(
            update(MeetingDocumentVersion)
            .where(MeetingDocumentVersion.document_id == document_id)
            .values(is_selected=False)
        )
        target.is_selected = True
        return {"version": version}


@router.post("/documents/{document_id}/regenerate")
async def regenerate_document(
    document_id: UUID, payload: DocumentRegenerate, principal: MeetingsKeyDep
) -> dict[str, object]:
    """Make a new model version with the type's current published prompt."""
    tenant_id, user_id = _personal(principal)
    await ratelimit.enforce(f"jn-doc:{user_id}", 30, 3600)
    async with session_scope(tenant_id) as session:
        document = await _owned_document(session, tenant_id, user_id, document_id, lock=True)
        if document.status in ("queued", "running"):
            raise ApiError("document_input_invalid", "این سند در حال ساخت است؛ کمی صبر کنید.")
        code = document.output_type_code
    async with control_session_scope() as control:
        _type, version = await jalase_output_types.published_version(control, code)
        values = (
            jalase_output_types.validate_input_values(version.input_fields, payload.input_values)
            if payload.input_values is not None
            else None
        )
        version_number = version.version
    async with session_scope(tenant_id) as session:
        document = await _owned_document(session, tenant_id, user_id, document_id, lock=True)
        document.output_type_version = version_number
        if values is not None:
            document.input_values = values
        if payload.note is not None:
            document.user_note = payload.note.strip()
        await meeting_documents.reopen(session, document)
        out = _document_out(document)
    await _enqueue_document(tenant_id, document_id)
    return out


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, principal: MeetingsKeyDep) -> None:
    tenant_id, user_id = _personal(principal)
    async with session_scope(tenant_id) as session:
        document = await _owned_document(session, tenant_id, user_id, document_id, lock=True)
        await session.delete(document)


DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/documents/{document_id}/export")
async def export_document(
    document_id: UUID,
    principal: MeetingsKeyDep,
    export_format: Annotated[Literal["pdf", "docx"], Query(alias="format")] = "pdf",
) -> Response:
    """The selected version as a PDF or Word file (private, never cached)."""
    tenant_id, user_id = _personal(principal)
    await ratelimit.enforce(f"jn-export:{user_id}", 60, 3600)
    async with session_scope(tenant_id) as session:
        document = await _owned_document(session, tenant_id, user_id, document_id)
        chosen = await _selected_version(session, document_id)
        if document.status != "done" or chosen is None:
            raise ApiError(
                "document_not_found", "سند هنوز آماده نیست؛ پس از ساخت آن را دریافت کنید."
            )
        markdown, code, meeting_id = chosen.markdown, document.output_type_code, document.meeting_id
        meeting = await session.get(Meeting, meeting_id)
        meeting_title = (meeting.title if meeting else None) or "جلسه"
    async with control_session_scope() as control:
        row = (
            await control.execute(
                select(JalaseOutputType.title_fa).where(JalaseOutputType.code == code)
            )
        ).scalar_one_or_none()
    kind = row or code
    first = markdown.strip().splitlines()[0] if markdown.strip() else ""
    title = first.lstrip("# ").strip() if first.startswith("#") else kind
    if export_format == "docx":
        content = document_docx.render(markdown)
        headers = {
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="jalase-document-{document_id}.docx"',
        }
        return Response(content, media_type=DOCX_TYPE, headers=headers)
    return await document_pdf.download(
        document_pdf.Document(
            title=title,
            kind=kind,
            metadata=[("جلسه", meeting_title), ("دسته", kind)],
            markdown=markdown,
        ),
        "jalase-document",
        document_id,
    )


# ---- plans, usage and purchases (personal accounts) ---------------------------------------


class OrderCreate(BaseModel):
    model_config = {"extra": "forbid"}
    plan_code: str = Field(pattern=r"^[a-z0-9_]{2,32}$")


class TokenOrderCreate(BaseModel):
    model_config = {"extra": "forbid"}
    package_id: UUID


class PayCreate(BaseModel):
    model_config = {"extra": "forbid"}
    gateway: Literal["zarinpal", "zibal", "saman", "behpardakht"] | None = None


@router.get("/plans")
async def list_plans(principal: MeetingsKeyDep) -> dict[str, object]:
    tenant_id, _ = _personal(principal)
    async with session_scope(tenant_id) as session:
        paid = await jalase_billing.plans(session)
        free = await jalase_billing.free_plan(session)
    return {"free": free, "plans": paid}


@router.get("/usage")
async def get_usage(principal: MeetingsKeyDep) -> dict[str, object]:
    tenant_id, _ = _personal(principal)
    async with session_scope(tenant_id) as session:
        return await jalase_billing.usage(session, tenant_id)


@router.get("/token-packages")
async def list_token_packages(principal: MeetingsKeyDep) -> list[dict[str, object]]:
    _personal(principal)
    async with control_session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(TokenPackage)
                    .where(TokenPackage.active.is_(True), TokenPackage.product == "jalase_negar")
                    .order_by(TokenPackage.tokens)
                )
            )
            .scalars()
            .all()
        )
        per_hour = await platform.jalase_tokens_per_hour(session)
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "hours": jalase_billing.to_hours(row.tokens, per_hour),
            "price_toman": row.price_toman,
        }
        for row in rows
    ]


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_plan_order(
    payload: OrderCreate,
    request: Request,
    principal: MeetingsKeyDep,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> dict[str, object]:
    tenant_id, user_id = _personal(principal)
    await ratelimit.enforce(f"jn-order:{user_id}", 20, 3600)
    async with session_scope(tenant_id) as session:
        tenant = await session.get(Tenant, tenant_id)
        user = await session.get(User, user_id)
        if tenant is None or user is None or tenant.product != jalase_accounts.PRODUCT:
            raise ApiError("forbidden", "این بخش فقط برای حساب شخصی جلسه‌نگار است.")
        order = await commerce.create_subscription_order(
            session,
            tenant=tenant,
            plan_code=payload.plan_code,
            period="monthly",
            extra_operators=0,
            customer_name=user.display_name or jalase_accounts.DEFAULT_NAME,
            customer_email=user.email,
            customer_mobile=user.mobile_number or "",
            invoice_profile={},
            idempotency_key=idempotency_key,
            product=jalase_accounts.PRODUCT,
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=user_id,
            tenant_id=tenant_id,
            action="order.created",
            payload={"order_id": str(order.id), "kind": order.kind},
            ip=client_ip(request),
        )
        return {"id": str(order.id), "amount_toman": order.amount_toman, "status": order.status}


@router.post("/token-orders", status_code=status.HTTP_201_CREATED)
async def create_token_order(
    payload: TokenOrderCreate,
    request: Request,
    principal: MeetingsKeyDep,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> dict[str, object]:
    tenant_id, user_id = _personal(principal)
    await ratelimit.enforce(f"jn-order:{user_id}", 20, 3600)
    async with session_scope(tenant_id) as session:
        return await token_packages.create_pack_order(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            package_id=payload.package_id,
            idempotency_key=idempotency_key,
            product=jalase_accounts.PRODUCT,
            ip=client_ip(request),
        )


@router.post("/orders/{order_id}/pay")
async def pay_order(
    order_id: UUID, request: Request, principal: MeetingsKeyDep, payload: PayCreate | None = None
) -> dict[str, object]:
    tenant_id, user_id = _personal(principal)
    async with session_scope(tenant_id) as session:
        order = (
            await session.execute(
                select(Order)
                .where(Order.id == order_id, Order.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise ApiError("not_found", "سفارش پیدا نشد؛ صفحه را تازه کنید.")
        attempt, redirect = await payments.initiate(
            session, order, payload.gateway if payload else None
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=user_id,
            tenant_id=tenant_id,
            action="payment.initiated",
            payload={"order_id": str(order.id), "gateway": attempt.gateway},
            ip=client_ip(request),
        )
        return {"payment_id": str(attempt.id), "redirect_url": redirect["url"]}


@router.get("/orders/{order_id}")
async def order_status(order_id: UUID, principal: MeetingsKeyDep) -> dict[str, object]:
    """Poll after the payment page closes: the order is `paid` once the gateway confirms."""
    tenant_id, _ = _personal(principal)
    async with session_scope(tenant_id) as session:
        order = (
            await session.execute(
                select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if order is None:
            raise ApiError("not_found", "سفارش پیدا نشد؛ صفحه را تازه کنید.")
        return {
            "id": str(order.id),
            "kind": order.kind,
            "status": order.status,
            "amount_toman": order.amount_toman,
            "paid_at": order.paid_at,
        }


# ---- progress, badges and friend invites --------------------------------------------------


class InviteRedeem(BaseModel):
    model_config = {"extra": "forbid"}
    code: str = Field(min_length=6, max_length=12, pattern=r"^[A-Za-z0-9]+$")


@router.get("/progress")
async def get_progress(principal: MeetingsKeyDep) -> dict[str, object]:
    """Level, badges and the month's gift allowance; also awards any badge just reached."""
    tenant_id, _ = _personal(principal)
    return await jalase_rewards.progress(tenant_id)


@router.get("/invite")
async def get_invite(principal: MeetingsKeyDep) -> dict[str, object]:
    tenant_id, _ = _personal(principal)
    return await jalase_rewards.invite_info(tenant_id)


@router.post("/invite/redeem")
async def redeem_invite(payload: InviteRedeem, principal: MeetingsKeyDep) -> dict[str, object]:
    tenant_id, user_id = _personal(principal)
    await ratelimit.enforce(f"jn-invite:{user_id}", 10, 3600)
    result = await jalase_rewards.redeem(tenant_id, payload.code)
    return {"ok": True, "tokens": result["tokens"]}


# ---- link to a SedaSanj organization ------------------------------------------------------


class LinkCreate(BaseModel):
    model_config = {"extra": "forbid"}
    pairing_code: str = Field(min_length=6, max_length=32)
    device_label: str = Field(min_length=1, max_length=80)
    app_version: str = Field(min_length=1, max_length=40)
    platform: Literal["android", "ios"]


@router.get("/link")
async def get_links(principal: MeetingsKeyDep) -> dict[str, object]:
    tenant_id, _ = _personal(principal)
    async with control_session_scope() as session:
        return {"items": await jalase_links.list_links(session, tenant_id)}


@router.post("/link", status_code=status.HTTP_201_CREATED)
async def create_link(
    payload: LinkCreate, request: Request, principal: MeetingsKeyDep
) -> dict[str, object]:
    """Swap an organization's pairing code for an organization device key (returned once)."""
    tenant_id, user_id = _personal(principal)
    await ratelimit.enforce(f"jn-link:{user_id}", 10, 3600)
    async with control_session_scope() as session:
        return await jalase_links.link(
            session,
            personal_tenant_id=tenant_id,
            personal_user_id=user_id,
            payload=MeetingPairIn(**payload.model_dump()),
            ip=client_ip(request),
        )


class LinkImport(BaseModel):
    model_config = {"extra": "forbid"}
    meeting_ids: list[UUID] = Field(min_length=1, max_length=jalase_links.IMPORT_MAX)


@router.post("/link/{link_id}/import")
async def import_into_link(
    link_id: UUID, payload: LinkImport, principal: MeetingsKeyDep
) -> dict[str, object]:
    """Copy chosen finished personal meetings into the linked organization (originals stay)."""
    tenant_id, user_id = _personal(principal)
    async with control_session_scope() as session:
        return await jalase_links.import_meetings(
            session,
            personal_tenant_id=tenant_id,
            personal_user_id=user_id,
            link_id=link_id,
            meeting_ids=payload.meeting_ids,
        )


@router.delete("/link/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(link_id: UUID, principal: MeetingsKeyDep) -> Response:
    tenant_id, user_id = _personal(principal)
    async with control_session_scope() as session:
        await jalase_links.revoke(session, tenant_id, user_id, link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
