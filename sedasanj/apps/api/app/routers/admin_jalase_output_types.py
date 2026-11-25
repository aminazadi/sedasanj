"""Admin management of the Jalase-Negar output types (conversion categories)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import StaffDep, StaffSession, SuperAdminDep, client_ip
from app.errors import ApiError
from app.models import HelpMedia, JalaseOutputType, JalaseOutputTypeVersion
from app.services import audit
from app.services import jalase_output_types as types

router = APIRouter(prefix="/v1/admin/jalase/output-types", tags=["admin"])


def _checked_icon(icon: str) -> str:
    if icon not in types.MENU_ICONS:
        raise ApiError(
            "output_type_icon_invalid",
            "آیکن انتخاب‌شده در فهرست آیکن‌ها نیست؛ یکی از فهرست را انتخاب کنید.",
        )
    return icon


class TypeCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    title_fa: str = Field(min_length=2, max_length=120)
    description_fa: str = Field(default="", max_length=500)
    menu_label_fa: str = Field(min_length=2, max_length=60)
    icon: str = Field(default=types.DEFAULT_MENU_ICON, max_length=40)
    thumbnail_media_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)


class TypeUpdate(BaseModel):
    title_fa: str | None = Field(default=None, min_length=2, max_length=120)
    description_fa: str | None = Field(default=None, max_length=500)
    menu_label_fa: str | None = Field(default=None, min_length=2, max_length=60)
    icon: str | None = Field(default=None, max_length=40)
    thumbnail_media_id: UUID | None = None
    clear_thumbnail: bool = False
    sort_order: int | None = Field(default=None, ge=0, le=100000)


class DraftUpdate(BaseModel):
    mode: Literal["summarize", "transform"] | None = None
    map_instruction: str | None = Field(default=None, max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=8000)
    input_fields: list[dict[str, Any]] | None = None
    llm_provider: str | None = Field(default=None, max_length=40)
    llm_model: str | None = Field(default=None, max_length=120)


def _version_out(version: JalaseOutputTypeVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "version": version.version,
        "state": version.state,
        "mode": version.mode,
        "map_instruction": version.map_instruction,
        "system_prompt": version.system_prompt,
        "input_fields": version.input_fields,
        "llm_provider": version.llm_provider,
        "llm_model": version.llm_model,
        "published_at": version.published_at,
        "created_at": version.created_at,
    }


def _type_out(
    output_type: JalaseOutputType, versions: list[JalaseOutputTypeVersion]
) -> dict[str, Any]:
    return {
        "id": str(output_type.id),
        "code": output_type.code,
        "title_fa": output_type.title_fa,
        "description_fa": output_type.description_fa,
        "menu_label_fa": output_type.menu_label_fa,
        "icon": output_type.icon,
        "thumbnail_url": types.thumbnail_url(output_type.thumbnail_media_id),
        "thumbnail_media_id": (
            str(output_type.thumbnail_media_id) if output_type.thumbnail_media_id else None
        ),
        "sort_order": output_type.sort_order,
        "status": output_type.status,
        "builtin": output_type.builtin,
        "updated_at": output_type.updated_at,
        "versions": [_version_out(v) for v in versions],
    }


async def _check_thumbnail(session: StaffSession, media_id: UUID | None) -> None:
    if media_id is None:
        return
    media = await session.get(HelpMedia, media_id)
    if media is None or media.kind != "image":
        raise ApiError(
            "output_type_invalid", "تصویر را از کتابخانهٔ رسانهٔ راهنما انتخاب کنید (فقط تصویر)."
        )


async def _audit(
    session: StaffSession, staff: Any, request: Request, action: str, output_type: JalaseOutputType
) -> None:
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action=f"jalase.output_type.{action}",
        payload={"code": output_type.code},
        ip=client_ip(request),
    )


@router.get("")
async def list_types(_: StaffDep, session: StaffSession) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(JalaseOutputType).order_by(
                    JalaseOutputType.sort_order, JalaseOutputType.code
                )
            )
        )
        .scalars()
        .all()
    )
    return [_type_out(row, await types.versions_of(session, row.id)) for row in rows]


@router.get("/{type_id}")
async def get_type(type_id: UUID, _: StaffDep, session: StaffSession) -> dict[str, Any]:
    row = await types.get_type(session, type_id)
    return _type_out(row, await types.versions_of(session, row.id))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_type(
    payload: TypeCreate, request: Request, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    await _check_thumbnail(session, payload.thumbnail_media_id)
    existing = (
        await session.execute(
            select(JalaseOutputType.id).where(JalaseOutputType.code == payload.code)
        )
    ).first()
    if existing is not None:
        raise ApiError(
            "output_type_code_taken", "این کد قبلاً استفاده شده است؛ کد دیگری انتخاب کنید."
        )
    row = JalaseOutputType(
        code=payload.code,
        title_fa=payload.title_fa.strip(),
        description_fa=payload.description_fa.strip(),
        menu_label_fa=payload.menu_label_fa.strip(),
        icon=_checked_icon(payload.icon),
        thumbnail_media_id=payload.thumbnail_media_id,
        sort_order=payload.sort_order
        if payload.sort_order is not None
        else await types.next_sort_order(session),
        status="draft",
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ApiError(
            "output_type_code_taken", "این کد قبلاً استفاده شده است؛ کد دیگری انتخاب کنید."
        ) from exc
    # An empty first draft so the editor has something to fill in.
    session.add(
        JalaseOutputTypeVersion(
            output_type_id=row.id, version=1, state="draft", created_by=staff.id
        )
    )
    await session.flush()
    await _audit(session, staff, request, "create", row)
    return _type_out(row, await types.versions_of(session, row.id))


@router.patch("/{type_id}")
async def update_type(
    type_id: UUID,
    payload: TypeUpdate,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, Any]:
    row = await types.get_type(session, type_id, lock=True)
    if payload.icon is not None:
        row.icon = _checked_icon(payload.icon)
    if payload.thumbnail_media_id is not None:
        await _check_thumbnail(session, payload.thumbnail_media_id)
        row.thumbnail_media_id = payload.thumbnail_media_id
    elif payload.clear_thumbnail:
        row.thumbnail_media_id = None
    for field in ("title_fa", "description_fa", "menu_label_fa"):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value.strip())
    if payload.sort_order is not None:
        row.sort_order = payload.sort_order
    row.updated_at = datetime.now(UTC)
    await session.flush()
    await _audit(session, staff, request, "update", row)
    return _type_out(row, await types.versions_of(session, row.id))


@router.put("/{type_id}/draft")
async def save_draft(
    type_id: UUID,
    payload: DraftUpdate,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, Any]:
    row = await types.get_type(session, type_id, lock=True)
    await types.save_draft(session, row, payload.model_dump(exclude_unset=True), staff.id)
    await _audit(session, staff, request, "draft", row)
    return _type_out(row, await types.versions_of(session, row.id))


@router.post("/{type_id}/publish")
async def publish(
    type_id: UUID, request: Request, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    row = await types.get_type(session, type_id, lock=True)
    await types.publish(session, row)
    await _audit(session, staff, request, "publish", row)
    return _type_out(row, await types.versions_of(session, row.id))


@router.post("/{type_id}/archive")
async def archive(
    type_id: UUID, request: Request, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    row = await types.get_type(session, type_id, lock=True)
    await types.archive(session, row)
    await _audit(session, staff, request, "archive", row)
    return _type_out(row, await types.versions_of(session, row.id))
