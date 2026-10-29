from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import OrgAdminDep, TenantSession, UserDep, client_ip
from app.errors import ApiError
from app.models import Contact
from app.schemas import (
    ContactImportError,
    ContactImportReport,
    ContactIn,
    ContactOut,
    ContactPage,
    ContactUpdate,
)
from app.services import audit, contacts, iran_geo, ratelimit

router = APIRouter(prefix="/v1/contacts", tags=["contacts"])

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
_DUPLICATE_HELP = "این شماره قبلاً در دفترچه تلفن ثبت شده؛ مخاطب موجود را ویرایش کنید"


def _invalid(reason: str | None) -> ApiError:
    return ApiError("invalid_request", reason or "اطلاعات مخاطب نامعتبر است")


async def _get(session: AsyncSession, tenant_id: UUID, contact_id: UUID) -> Contact:
    contact = (
        await session.execute(
            select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if contact is None:
        raise ApiError("not_found", "مخاطب پیدا نشد؛ فهرست را تازه کنید")
    return contact


async def _number_taken(
    session: AsyncSession, tenant_id: UUID, number: str, *, exclude: UUID | None = None
) -> bool:
    query = select(Contact.id).where(Contact.tenant_id == tenant_id, Contact.phone_number == number)
    if exclude is not None:
        query = query.where(Contact.id != exclude)
    return (await session.execute(query.limit(1))).first() is not None


def _search_filter(q: str) -> object:
    pattern = f"%{q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
    digits = contacts.phone_key(q) if any(ch.isdigit() for ch in q) else None
    clauses = [
        Contact.name.ilike(pattern, escape="\\"),
        Contact.company.ilike(pattern, escape="\\"),
        Contact.email.ilike(pattern, escape="\\"),
        Contact.province.ilike(pattern, escape="\\"),
        Contact.city.ilike(pattern, escape="\\"),
    ]
    if digits is not None:
        clauses.append(Contact.phone_number.like(f"%{digits.lstrip('0')}%"))
    return or_(*clauses)


@router.get("", response_model=ContactPage)
async def list_contacts(
    principal: UserDep,
    session: TenantSession,
    q: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ContactPage:
    assert principal.tenant_id is not None
    stmt = select(Contact).where(Contact.tenant_id == principal.tenant_id)
    if q and q.strip():
        stmt = stmt.where(_search_filter(q.strip()))  # type: ignore[arg-type]
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = (
        (await session.execute(stmt.order_by(Contact.name, Contact.id).offset(offset).limit(limit)))
        .scalars()
        .all()
    )
    return ContactPage(
        items=[ContactOut.model_validate(row) for row in rows],
        total=total,
        page=offset // limit + 1,
        page_size=limit,
        pages=max(1, (total + limit - 1) // limit),
    )


@router.get("/geo")
async def contacts_geo(principal: UserDep, response: Response) -> dict[str, Any]:
    """Iran provinces with their cities, for the phonebook drop-downs."""
    response.headers["Cache-Control"] = "private, max-age=86400"
    return iran_geo.dataset()


@router.get("/export")
async def export_contacts(
    request: Request, principal: OrgAdminDep, session: TenantSession
) -> Response:
    assert principal.tenant_id is not None
    await ratelimit.enforce(f"contacts-export:{principal.id}", 10)
    rows = (
        (
            await session.execute(
                select(Contact)
                .where(Contact.tenant_id == principal.tenant_id)
                .order_by(Contact.name, Contact.id)
            )
        )
        .scalars()
        .all()
    )
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="contacts.export",
        payload={"count": len(rows)},
        ip=client_ip(request),
    )
    return Response(
        contacts.export_csv(rows),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="contacts.csv"'},
    )


@router.get("/template")
async def contacts_template(principal: OrgAdminDep) -> Response:
    return Response(
        contacts.template_csv(),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="contacts-template.csv"'},
    )


@router.post("/import", response_model=ContactImportReport)
async def import_contacts(
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
    file: Annotated[UploadFile, File()],
    mode: Annotated[Literal["skip", "update"], Form()] = "skip",
    dry_run: Annotated[bool, Form()] = False,
) -> ContactImportReport:
    assert principal.tenant_id is not None
    await ratelimit.enforce(
        f"contacts-import:{principal.id}", get_settings().rate_limit_uploads_per_minute
    )
    raw = await file.read(contacts.MAX_IMPORT_BYTES + 1)
    if len(raw) > contacts.MAX_IMPORT_BYTES:
        limit_mb = contacts.MAX_IMPORT_BYTES // (1024 * 1024)
        raise ApiError(
            "invalid_request", f"حجم فایل بیش از {limit_mb} مگابایت است؛ فایل را تقسیم کنید"
        )
    parsed = contacts.parse_import(raw)
    try:
        outcome = await contacts.apply_import(
            session,
            principal.tenant_id,
            parsed,
            mode=mode,
            dry_run=dry_run,
            created_by=principal.id,
        )
    except IntegrityError as exc:
        raise ApiError(
            "conflict", "همزمان مخاطب دیگری با همین شماره ثبت شد؛ ایمپورت را دوباره اجرا کنید"
        ) from exc
    if not dry_run:
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="contacts.import",
            payload={
                "mode": mode,
                "created": outcome.created,
                "updated": outcome.updated,
                "skipped": outcome.skipped,
                "errors": parsed.error_count,
            },
            ip=client_ip(request),
        )
    return ContactImportReport(
        dry_run=dry_run,
        mode=mode,
        total_rows=parsed.total_rows,
        created=outcome.created,
        updated=outcome.updated,
        skipped=outcome.skipped,
        error_count=parsed.error_count,
        errors=[ContactImportError(row=row, message=message) for row, message in parsed.errors],
    )


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactIn, principal: OrgAdminDep, session: TenantSession
) -> ContactOut:
    assert principal.tenant_id is not None
    fields, reason = contacts.validate_fields(
        name=payload.name,
        phone=payload.phone_number,
        company=payload.company,
        email=payload.email,
        notes=payload.notes,
        province=payload.province,
        city=payload.city,
    )
    if fields is None:
        raise _invalid(reason)
    if await _number_taken(session, principal.tenant_id, fields.phone_number):
        raise ApiError("conflict", _DUPLICATE_HELP)
    contact = Contact(
        tenant_id=principal.tenant_id,
        phone_number=fields.phone_number,
        name=fields.name,
        company=fields.company,
        email=fields.email,
        province=fields.province,
        city=fields.city,
        notes=fields.notes,
        created_by=principal.id,
    )
    session.add(contact)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ApiError("conflict", _DUPLICATE_HELP) from exc
    await session.refresh(contact)
    return ContactOut.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: UUID, payload: ContactUpdate, principal: OrgAdminDep, session: TenantSession
) -> ContactOut:
    assert principal.tenant_id is not None
    contact = await _get(session, principal.tenant_id, contact_id)
    sent = payload.model_fields_set
    fields, reason = contacts.validate_fields(
        name=payload.name if "name" in sent and payload.name is not None else contact.name,
        phone=(
            payload.phone_number
            if "phone_number" in sent and payload.phone_number is not None
            else contact.phone_number
        ),
        company=payload.company if "company" in sent else contact.company,
        email=payload.email if "email" in sent else contact.email,
        notes=payload.notes if "notes" in sent else contact.notes,
        province=payload.province if "province" in sent else contact.province,
        city=payload.city if "city" in sent else contact.city,
    )
    if fields is None:
        raise _invalid(reason)
    if fields.phone_number != contact.phone_number and await _number_taken(
        session, principal.tenant_id, fields.phone_number, exclude=contact.id
    ):
        raise ApiError("conflict", _DUPLICATE_HELP)
    contact.name = fields.name
    contact.phone_number = fields.phone_number
    contact.company = fields.company
    contact.email = fields.email
    contact.province = fields.province
    contact.city = fields.city
    contact.notes = fields.notes
    contact.updated_at = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ApiError("conflict", _DUPLICATE_HELP) from exc
    await session.refresh(contact)
    return ContactOut.model_validate(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: UUID, request: Request, principal: OrgAdminDep, session: TenantSession
) -> Response:
    assert principal.tenant_id is not None
    contact = await _get(session, principal.tenant_id, contact_id)
    await session.delete(contact)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="contacts.delete",
        payload={"contact_id": str(contact_id)},
        ip=client_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
