"""Bounded tenant exports with authenticated downloads and retryable object cleanup."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import control_session_scope, session_scope
from app.deps import Principal
from app.errors import ApiError
from app.models import (
    CALL_TYPES,
    AssistantExport,
    Call,
    CallInsight,
    Contact,
    CrmOutcome,
    FollowUpTask,
    SalesInsight,
    Transcript,
)
from app.services import audit, contacts, follow_up_tasks, platform, ratelimit
from app.services.assistant_export_renderers import MEDIA_TYPES, render
from app.services.storage import get_storage

Dataset = Literal["calls_analysis", "contacts", "follow_up_tasks", "transcripts"]
ExportFormat = Literal["csv", "json", "xlsx", "pdf", "md", "txt"]
MAX_FILE_BYTES = 25 * 1024 * 1024
logger = logging.getLogger(__name__)


class ExportFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_date: datetime | None = None
    to_date: datetime | None = None
    operator_id: UUID | None = None
    status: str | None = Field(default=None, max_length=40)
    province: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    query: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("from_date", "to_date")
    @classmethod
    def utc_date(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


@dataclass(frozen=True)
class DatasetDefinition:
    columns: dict[str, str]
    row_cap: int
    loader: Callable[
        [AsyncSession, Principal, ExportFilters, Any, int],
        Awaitable[list[dict[str, Any]]],
    ]


CALL_COLUMNS = {
    "call_id": "شناسه تماس",
    "started_at": "زمان تماس",
    "duration_seconds": "مدت به ثانیه",
    "caller_number": "شماره تماس‌گیرنده",
    "dialed_number": "شماره مقصد",
    "agent_extension": "داخلی اپراتور",
    "direction": "جهت",
    "status": "وضعیت پردازش",
    "call_type": "نوع تماس",
    "summary": "خلاصه",
    "intent": "هدف",
    "sentiment": "احساس",
    "topics": "موضوع‌ها",
    "keywords": "کلیدواژه‌ها",
    "action_items": "اقدام‌ها",
    "sales_inference": "استنباط فروش",
    "crm_outcomes": "نتایج قطعی CRM",
}


def selected_columns(dataset: str, columns: list[str] | None) -> dict[str, str]:
    if dataset not in DATASETS:
        raise ApiError(
            "invalid_request", "دسته داده معتبر نیست؛ یکی از دسته‌های مجاز را انتخاب کنید"
        )
    available = DATASETS[dataset].columns
    if columns is None:
        return dict(available)
    if not columns or len(set(columns)) != len(columns) or any(c not in available for c in columns):
        raise ApiError(
            "invalid_request", "ستون‌ها معتبر نیستند؛ نام ستون‌های مجاز و یکتا را انتخاب کنید"
        )
    return {key: available[key] for key in columns}


def validate_filters(dataset: str, filters: ExportFilters, bound_call_id: UUID | None) -> None:
    if filters.from_date and filters.to_date and filters.from_date >= filters.to_date:
        raise ApiError("invalid_request", "شروع بازه باید پیش از پایان باشد؛ بازه را اصلاح کنید")
    if dataset != "contacts" and (filters.province or filters.city):
        raise ApiError("invalid_request", "فیلتر استان و شهر برای مخاطبان است؛ دسته را اصلاح کنید")
    if dataset == "contacts" and (
        filters.from_date
        or filters.to_date
        or filters.operator_id
        or filters.status
        or bound_call_id
    ):
        raise ApiError("invalid_request", "برای مخاطبان از فیلتر جست‌وجو، استان و شهر استفاده کنید")
    if dataset == "follow_up_tasks" and filters.status not in {None, "open", "done"}:
        raise ApiError("invalid_request", "وضعیت پیگیری را open یا done انتخاب کنید")
    if dataset == "contacts" and (filters.province or filters.city):
        _province, _city, reason = contacts.resolve_geo(filters.province, filters.city)
        if reason:
            raise ApiError("invalid_request", reason)


async def load_rows(
    session: AsyncSession,
    principal: Principal,
    dataset: str,
    filters: ExportFilters,
    *,
    bound_call_id: UUID | None = None,
) -> list[dict[str, Any]]:
    definition = DATASETS[dataset]
    visible = (
        None
        if dataset == "contacts"
        else await _visible_call_ids(
            session,
            principal,
            dataset,
            filters,
            bound_call_id,
        )
    )
    return await definition.loader(session, principal, filters, visible, definition.row_cap)


async def _visible_call_ids(
    session: AsyncSession,
    principal: Principal,
    dataset: str,
    filters: ExportFilters,
    bound_call_id: UUID | None,
) -> Any:
    from app.services.assistant_tools import ToolContext, _base_calls, _validate_operator

    ctx = ToolContext(session, principal, bound_call_id)
    operator_id = await _validate_operator(ctx, filters.operator_id)
    base = _base_calls(ctx)
    if operator_id is not None and principal.role != "operator":
        from app.models import CallOperatorAssignment

        base = base.where(
            select(CallOperatorAssignment.id)
            .where(
                CallOperatorAssignment.tenant_id == principal.tenant_id,
                CallOperatorAssignment.call_id == Call.id,
                CallOperatorAssignment.operator_id == operator_id,
                CallOperatorAssignment.superseded_at.is_(None),
            )
            .exists()
        )
    if filters.from_date:
        base = base.where(Call.started_at >= filters.from_date)
    if filters.to_date:
        base = base.where(Call.started_at <= filters.to_date)
    if filters.status and dataset != "follow_up_tasks":
        base = base.where(
            (Call.call_type if filters.status in CALL_TYPES else Call.status) == filters.status
        )
    return base.with_only_columns(Call.id)


async def _load_contacts(
    session: AsyncSession,
    principal: Principal,
    filters: ExportFilters,
    visible: Any,
    limit: int,
) -> list[dict[str, Any]]:
    if principal.role != "org_admin":
        raise ApiError("forbidden", "خروجی مخاطبان را از مدیر سازمان درخواست کنید")
    stmt: Any = select(Contact).where(Contact.tenant_id == principal.tenant_id)
    if filters.query:
        stmt = stmt.where(contacts.search_filter(filters.query.strip()))
    if filters.province:
        province, city, _reason = contacts.resolve_geo(filters.province, filters.city)
        stmt = stmt.where(Contact.province == province)
        if city:
            stmt = stmt.where(Contact.city == city)
    found = (
        (await session.execute(stmt.order_by(Contact.name, Contact.id).limit(limit + 1)))
        .scalars()
        .all()
    )
    return [{key: getattr(row, key) for key in DATASETS["contacts"].columns} for row in found]


async def _load_tasks(
    session: AsyncSession,
    principal: Principal,
    filters: ExportFilters,
    visible: Any,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(FollowUpTask, Call)
        .join(Call, Call.id == FollowUpTask.call_id)
        .where(FollowUpTask.tenant_id == principal.tenant_id, Call.id.in_(visible))
    )
    if filters.status:
        stmt = stmt.where(FollowUpTask.status == filters.status)
    if filters.query:
        stmt = stmt.where(FollowUpTask.title.icontains(filters.query, autoescape=True))
    task_rows = (
        await session.execute(
            stmt.order_by(FollowUpTask.created_at.desc(), FollowUpTask.id).limit(limit + 1)
        )
    ).all()
    return [
        follow_up_tasks.serialize(task, call).model_dump(mode="json") for task, call in task_rows
    ]


async def _load_transcripts(
    session: AsyncSession,
    principal: Principal,
    filters: ExportFilters,
    visible: Any,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(Call, Transcript)
        .join(
            Transcript,
            and_(Transcript.call_id == Call.id, Transcript.tenant_id == principal.tenant_id),
        )
        .where(Call.id.in_(visible))
    )
    if filters.query:
        stmt = stmt.where(
            func.coalesce(Transcript.corrected_text, Transcript.full_text).icontains(
                filters.query, autoescape=True
            )
        )
    transcript_rows = (
        await session.execute(stmt.order_by(Call.started_at.desc(), Call.id).limit(limit + 1))
    ).all()
    return [
        {
            "call_id": str(call.id),
            "started_at": call.started_at.isoformat(),
            "caller_number": call.caller_number,
            "dialed_number": call.dialed_number,
            "agent_extension": call.agent_extension,
            "transcript": transcript.corrected_text or transcript.full_text,
        }
        for call, transcript in transcript_rows
    ]


async def _load_calls_analysis(
    session: AsyncSession,
    principal: Principal,
    filters: ExportFilters,
    visible: Any,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(Call, CallInsight, SalesInsight)
        .outerjoin(
            CallInsight,
            and_(
                CallInsight.call_id == Call.id,
                CallInsight.tenant_id == principal.tenant_id,
            ),
        )
        .outerjoin(
            SalesInsight,
            and_(
                SalesInsight.call_id == Call.id,
                SalesInsight.tenant_id == principal.tenant_id,
            ),
        )
        .where(Call.id.in_(visible))
    )
    if filters.query:
        stmt = stmt.where(
            or_(
                Call.caller_number.icontains(filters.query, autoescape=True),
                Call.dialed_number.icontains(filters.query, autoescape=True),
                CallInsight.summary.icontains(filters.query, autoescape=True),
            )
        )
    call_rows = (
        await session.execute(stmt.order_by(Call.started_at.desc(), Call.id).limit(limit + 1))
    ).all()
    if len(call_rows) > limit:
        raise too_large(limit)
    outcomes: dict[UUID, list[dict[str, Any]]] = {}
    if call_rows:
        crm_rows = (
            await session.execute(
                select(CrmOutcome)
                .where(
                    CrmOutcome.tenant_id == principal.tenant_id,
                    CrmOutcome.call_id.in_([call.id for call, _insight, _sale in call_rows]),
                )
                .order_by(CrmOutcome.occurred_at, CrmOutcome.id)
            )
        ).scalars()
        for outcome in crm_rows:
            assert outcome.call_id is not None
            outcomes.setdefault(outcome.call_id, []).append(
                {
                    "outcome": outcome.outcome,
                    "amount": outcome.amount,
                    "currency": outcome.currency,
                    "product": outcome.product,
                }
            )
    return [
        {
            "call_id": str(call.id),
            "started_at": call.started_at.isoformat(),
            "duration_seconds": round(call.duration_ms / 1000),
            "caller_number": call.caller_number,
            "dialed_number": call.dialed_number,
            "agent_extension": call.agent_extension,
            "direction": call.direction,
            "status": call.status,
            "call_type": call.call_type,
            "summary": insight.summary if insight else None,
            "intent": insight.intent if insight else None,
            "sentiment": insight.sentiment if insight else None,
            "topics": insight.topics if insight else [],
            "keywords": insight.keywords if insight else [],
            "action_items": insight.action_items if insight else [],
            "sales_inference": {
                "outcome": sale.outcome,
                "certainty": sale.certainty,
                "confidence": sale.confidence,
                "product": sale.product,
                "next_action": sale.next_action,
            }
            if sale
            else None,
            "crm_outcomes": outcomes.get(call.id, []),
        }
        for call, insight, sale in call_rows
    ]


DATASETS = {
    "calls_analysis": DatasetDefinition(CALL_COLUMNS, 5000, _load_calls_analysis),
    "contacts": DatasetDefinition(
        {
            "name": "نام",
            "phone_number": "شماره تلفن",
            "company": "شرکت",
            "email": "ایمیل",
            "province": "استان",
            "city": "شهر",
            "notes": "توضیحات",
        },
        5000,
        _load_contacts,
    ),
    "follow_up_tasks": DatasetDefinition(
        {
            "id": "شناسه پیگیری",
            "call_id": "شناسه تماس",
            "title": "عنوان",
            "description": "توضیحات",
            "status": "وضعیت",
            "priority": "اولویت",
            "due_date": "تاریخ سررسید",
            "source_phone": "شماره مبدأ",
            "caller_number": "شماره تماس‌گیرنده",
            "dialed_number": "شماره مقصد",
            "agent_extension": "داخلی اپراتور",
            "created_at": "زمان ایجاد",
            "completed_at": "زمان انجام",
            "updated_at": "زمان ویرایش",
        },
        5000,
        _load_tasks,
    ),
    "transcripts": DatasetDefinition(
        {
            "call_id": "شناسه تماس",
            "started_at": "زمان تماس",
            "caller_number": "شماره تماس‌گیرنده",
            "dialed_number": "شماره مقصد",
            "agent_extension": "داخلی اپراتور",
            "transcript": "متن مکالمه",
        },
        500,
        _load_transcripts,
    ),
}


def too_large(limit: int) -> ApiError:
    return ApiError(
        "export_too_large", f"خروجی بیش از {limit} ردیف دارد؛ بازه یا فیلترها را محدود کنید"
    )


def expiry_notice(expires_at: datetime, minutes: int) -> str:
    local = expires_at.astimezone(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M")
    remaining = "۱ ساعت دیگر" if minutes == 60 else f"{minutes} دقیقه دیگر"
    return f"این فایل تا {local} به وقت تهران ({remaining}) معتبر است و پس از آن حذف می‌شود."


async def create_export(
    session: AsyncSession,
    principal: Principal,
    dataset: str,
    fmt: str,
    filters: ExportFilters,
    columns: list[str] | None = None,
    *,
    conversation_id: UUID | None = None,
    bound_call_id: UUID | None = None,
) -> dict[str, Any]:
    if (
        principal.kind != "user"
        or principal.role not in {"org_admin", "operator"}
        or principal.tenant_id is None
    ):
        raise ApiError("forbidden", "با حساب کاربری سازمان وارد شوید و دوباره درخواست خروجی بدهید")
    if dataset == "contacts" and principal.role != "org_admin":
        raise ApiError("forbidden", "خروجی مخاطبان را از مدیر سازمان درخواست کنید")
    chosen = selected_columns(dataset, columns)
    if fmt not in MEDIA_TYPES:
        raise ApiError("invalid_request", "یکی از قالب‌های مجاز خروجی را انتخاب کنید")
    validate_filters(dataset, filters, bound_call_id)
    await ratelimit.enforce(f"assistant-export:{principal.id}", 5)
    rows = await load_rows(session, principal, dataset, filters, bound_call_id=bound_call_id)
    if len(rows) > DATASETS[dataset].row_cap:
        raise too_large(DATASETS[dataset].row_cap)
    body = await asyncio.to_thread(render, fmt, chosen, rows)
    if len(body) > MAX_FILE_BYTES:
        raise ApiError("export_too_large", "حجم خروجی بیش از حد مجاز است؛ فیلترها را محدود کنید")
    settings = await platform.effective_models(session)
    minutes = int(
        settings.get(
            "assistant_export_ttl_minutes", str(get_settings().assistant_export_ttl_minutes)
        )
    )
    now = datetime.now(UTC)
    export_id = uuid4()
    filename = f"{dataset}-{export_id.hex[:8]}.{fmt}"
    key = f"exports/{principal.tenant_id}/{export_id}.{fmt}"
    row = AssistantExport(
        id=export_id,
        tenant_id=principal.tenant_id,
        user_id=principal.id,
        conversation_id=conversation_id,
        dataset=dataset,
        format=fmt,
        filename=filename,
        storage_key=key,
        size_bytes=len(body),
        row_count=len(rows),
        filters=filters.model_dump(mode="json", exclude_none=True),
        expires_at=now + timedelta(minutes=minutes),
        created_at=now,
    )
    session.add(row)
    await session.flush()
    storage = get_storage()
    try:
        await storage.put(key, body, MEDIA_TYPES[fmt])
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="assistant.export.create",
            payload={"export_id": str(export_id), "dataset": dataset, "rows": len(rows)},
        )
    except BaseException:
        await storage.delete(key)
        raise
    file = {
        "export_id": str(export_id),
        "name": filename,
        "format": fmt,
        "size": len(body),
        "rows": len(rows),
        "expires_at": row.expires_at.isoformat(),
        "expires_in_minutes": minutes,
    }
    return {
        "version": 1,
        "count": len(rows),
        "file": file,
        "files": [file],
        "notice": expiry_notice(row.expires_at, minutes),
    }


async def purge_session(session: AsyncSession, tenant_id: UUID, *, batch_size: int = 100) -> int:
    now = datetime.now(UTC)
    rows = (
        (
            await session.execute(
                select(AssistantExport)
                .where(
                    AssistantExport.tenant_id == tenant_id,
                    or_(AssistantExport.expires_at <= now, AssistantExport.deleted_at.is_not(None)),
                )
                .order_by(AssistantExport.expires_at)
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
        )
        .scalars()
        .all()
    )
    storage = get_storage()
    for row in rows:
        # Keep the lock until commit. Failed object deletion leaves the ledger for a retry.
        await storage.delete(row.storage_key)
        row.deleted_at = now
        await session.delete(row)
    return len(rows)


async def export_tenant_ids() -> list[UUID]:
    # Deleted and suspended tenants still need their temporary files removed.
    from app.models import Tenant

    async with control_session_scope() as session:
        return list((await session.execute(select(Tenant.id))).scalars().all())


async def purge_expired() -> int:
    removed = 0
    failed = 0
    for tenant_id in await export_tenant_ids():
        try:
            while True:
                async with session_scope(tenant_id) as session:
                    batch = await purge_session(session, tenant_id)
                removed += batch
                if batch < 100:
                    break
        except Exception:
            failed += 1
            logger.error(
                "assistant export cleanup failed; check tenant storage and database access",
                extra={"extra_fields": {"tenant_id": str(tenant_id)}},
            )
    if failed:
        raise RuntimeError(
            f"assistant export cleanup failed for {failed} tenants; check worker logs"
        )
    return removed
