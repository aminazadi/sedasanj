"""Output types (conversion categories) of the Jalase-Negar app: validation, versioning, listing.

The admin defines the types. A published version is never edited: a change is a new draft that is
published later, so every document can name the exact prompt it was made with.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import JalaseOutputType, JalaseOutputTypeVersion

FIELD_TYPES = ("text", "select", "number")
MAX_FIELDS = 8
MAX_OPTIONS = 20
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,29}$")


def normalize_input_fields(raw: Any) -> list[dict[str, Any]]:
    """Validate the form fields the app shows for a type; returns the cleaned list."""
    if not isinstance(raw, list) or len(raw) > MAX_FIELDS:
        raise ApiError("output_type_invalid", f"حداکثر {MAX_FIELDS} فیلد ورودی مجاز است.")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError("output_type_invalid", "هر فیلد ورودی باید یک شیء باشد.")
        key = str(item.get("key", ""))
        label = str(item.get("label_fa", "")).strip()
        kind = str(item.get("type", "text"))
        if not _KEY.match(key) or key in seen:
            raise ApiError(
                "output_type_invalid",
                "کلید فیلد باید با حرف انگلیسی کوچک شروع شود و یکتا باشد (حروف کوچک، عدد و _).",
            )
        if not label or len(label) > 80 or kind not in FIELD_TYPES:
            raise ApiError("output_type_invalid", "عنوان فارسی و نوع فیلد را درست وارد کنید.")
        entry: dict[str, Any] = {
            "key": key,
            "label_fa": label,
            "type": kind,
            "required": bool(item.get("required", False)),
            "max_len": min(max(int(item.get("max_len", 200)), 1), 500),
        }
        if kind == "select":
            options = item.get("options")
            if (
                not isinstance(options, list)
                or not 2 <= len(options) <= MAX_OPTIONS
                or not all(isinstance(o, str) and 0 < len(o.strip()) <= 80 for o in options)
            ):
                raise ApiError("output_type_invalid", "فیلد انتخابی دست‌کم دو گزینهٔ معتبر می‌خواهد.")
            entry["options"] = [o.strip() for o in options]
        seen.add(key)
        cleaned.append(entry)
    return cleaned


def check_prompt(mode: str, map_instruction: str, system_prompt: str) -> None:
    if len(system_prompt) > 8000 or len(map_instruction) > 4000:
        raise ApiError("output_type_invalid", "متن پرامپت بیش از حد بلند است.")
    if mode == "summarize" and not map_instruction.strip():
        raise ApiError("output_type_invalid", "برای حالت خلاصه‌سازی دستور خلاصهٔ هر بخش لازم است.")


async def get_type(session: AsyncSession, type_id: UUID, *, lock: bool = False) -> JalaseOutputType:
    statement = select(JalaseOutputType).where(JalaseOutputType.id == type_id)
    if lock:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).scalar_one_or_none()
    if row is None:
        raise ApiError("output_type_not_found", "دستهٔ تبدیل پیدا نشد.")
    return row


async def versions_of(session: AsyncSession, type_id: UUID) -> list[JalaseOutputTypeVersion]:
    return list(
        (
            await session.execute(
                select(JalaseOutputTypeVersion)
                .where(JalaseOutputTypeVersion.output_type_id == type_id)
                .order_by(JalaseOutputTypeVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )


async def save_draft(
    session: AsyncSession, output_type: JalaseOutputType, values: dict[str, Any], staff_id: UUID
) -> JalaseOutputTypeVersion:
    """Create or update the single draft; a new draft starts from the latest version."""
    if output_type.builtin:
        raise ApiError(
            "output_type_builtin_locked",
            "پرامپت این دسته داخلی است؛ فقط عنوان، توضیح و تصویر را می‌توان تغییر داد.",
        )
    versions = await versions_of(session, output_type.id)
    draft = next((v for v in versions if v.state == "draft"), None)
    if draft is None:
        base = versions[0] if versions else None
        draft = JalaseOutputTypeVersion(
            output_type_id=output_type.id,
            version=(base.version if base else 0) + 1,
            state="draft",
            mode=base.mode if base else "summarize",
            map_instruction=base.map_instruction if base else "",
            system_prompt=base.system_prompt if base else "",
            input_fields=list(base.input_fields) if base else [],
            llm_provider=base.llm_provider if base else None,
            llm_model=base.llm_model if base else None,
            created_by=staff_id,
        )
        session.add(draft)
    for field in ("mode", "map_instruction", "system_prompt", "llm_provider", "llm_model"):
        if field in values:
            setattr(draft, field, values[field])
    if "input_fields" in values:
        draft.input_fields = normalize_input_fields(values["input_fields"])
    check_prompt(draft.mode, draft.map_instruction, draft.system_prompt)
    output_type.updated_at = datetime.now(UTC)
    await session.flush()
    return draft


async def publish(session: AsyncSession, output_type: JalaseOutputType) -> JalaseOutputTypeVersion:
    """Make the draft the published version; the previous one becomes `superseded`."""
    if output_type.builtin:
        raise ApiError("output_type_builtin_locked", "این دستهٔ داخلی همیشه منتشر است.")
    versions = await versions_of(session, output_type.id)
    draft = next((v for v in versions if v.state == "draft"), None)
    if draft is None:
        raise ApiError("output_type_not_publishable", "پیش‌نویسی برای انتشار وجود ندارد.")
    if not draft.system_prompt.strip():
        raise ApiError("output_type_not_publishable", "پیش از انتشار پرامپت اصلی را بنویسید.")
    check_prompt(draft.mode, draft.map_instruction, draft.system_prompt)
    for version in versions:
        if version.state == "published":
            version.state = "superseded"
    await session.flush()
    draft.state = "published"
    draft.published_at = datetime.now(UTC)
    output_type.status = "published"
    output_type.updated_at = datetime.now(UTC)
    await session.flush()
    return draft


async def archive(session: AsyncSession, output_type: JalaseOutputType) -> None:
    if output_type.builtin:
        raise ApiError("output_type_builtin_locked", "دستهٔ داخلی را نمی‌توان بایگانی کرد.")
    output_type.status = "archived"
    output_type.updated_at = datetime.now(UTC)
    await session.flush()


async def published_catalog(session: AsyncSession) -> list[dict[str, Any]]:
    """What the app shows: published types with the published version's input fields."""
    rows = (
        await session.execute(
            select(JalaseOutputType, JalaseOutputTypeVersion)
            .join(
                JalaseOutputTypeVersion,
                (JalaseOutputTypeVersion.output_type_id == JalaseOutputType.id)
                & (JalaseOutputTypeVersion.state == "published"),
            )
            .where(JalaseOutputType.status == "published")
            .order_by(JalaseOutputType.sort_order, JalaseOutputType.code)
        )
    ).all()
    return [
        {
            "code": output_type.code,
            "title": output_type.title_fa,
            "description": output_type.description_fa,
            "menu_label": output_type.menu_label_fa,
            "thumbnail_url": thumbnail_url(output_type.thumbnail_media_id),
            "mode": version.mode,
            "automatic": output_type.builtin,
            "version": version.version,
            "input_fields": version.input_fields,
        }
        for output_type, version in rows
    ]


def thumbnail_url(media_id: UUID | None) -> str | None:
    return f"/v1/help/media/{media_id}" if media_id else None


async def next_sort_order(session: AsyncSession) -> int:
    top = (
        await session.execute(select(func.coalesce(func.max(JalaseOutputType.sort_order), 0)))
    ).scalar_one()
    return int(top) + 10


def validate_input_values(fields: list[dict[str, Any]], raw: Any) -> dict[str, str]:
    """Check what the user typed against the type's fields; returns the cleaned values.

    Unknown keys are rejected so nothing the form does not define reaches the prompt.
    """
    values = raw if isinstance(raw, dict) else {}
    known = {field["key"]: field for field in fields}
    extra = set(values) - set(known)
    if extra:
        raise ApiError("document_input_invalid", "فیلد ناشناخته در ورودی سند فرستاده شده است.")
    cleaned: dict[str, str] = {}
    for key, field in known.items():
        value = values.get(key)
        text_value = "" if value is None else str(value).strip()
        if not text_value:
            if field.get("required"):
                raise ApiError("document_input_invalid", f"«{field['label_fa']}» را وارد کنید.")
            continue
        if len(text_value) > int(field.get("max_len", 200)):
            raise ApiError("document_input_invalid", f"«{field['label_fa']}» بیش از حد بلند است.")
        if field["type"] == "select" and text_value not in field.get("options", []):
            raise ApiError("document_input_invalid", f"«{field['label_fa']}» یکی از گزینه‌ها نیست.")
        if field["type"] == "number":
            try:
                float(text_value)
            except ValueError as exc:
                raise ApiError(
                    "document_input_invalid", f"«{field['label_fa']}» باید عدد باشد."
                ) from exc
        cleaned[key] = text_value
    return cleaned


async def published_version(
    session: AsyncSession, code: str
) -> tuple[JalaseOutputType, JalaseOutputTypeVersion]:
    """The type and its published version, or `output_type_not_found` (drafts are invisible)."""
    row = (
        await session.execute(
            select(JalaseOutputType, JalaseOutputTypeVersion)
            .join(
                JalaseOutputTypeVersion,
                (JalaseOutputTypeVersion.output_type_id == JalaseOutputType.id)
                & (JalaseOutputTypeVersion.state == "published"),
            )
            .where(JalaseOutputType.code == code, JalaseOutputType.status == "published")
        )
    ).first()
    if row is None:
        raise ApiError("output_type_not_found", "این دسته وجود ندارد یا منتشر نشده است.")
    return row[0], row[1]
