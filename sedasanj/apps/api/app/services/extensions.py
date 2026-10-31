"""PBX extensions synced from the FreePBX module.

An extension can be linked to a phonebook contact and to an operator. The operator link is kept
in sync with `users.extension`, which call ownership (`operator_scope`) already relies on.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Call, Contact, PbxExtension, User
from app.services.phone_numbers import normalize_call_number

MAX_SYNC_EXTENSIONS = 5000
_EXTENSION_RE = re.compile(r"^[0-9]{1,8}$")
_NAME_MAX = 200


@dataclass(frozen=True)
class SyncOutcome:
    created: int
    updated: int
    deactivated: int


def extension_key(value: str | None) -> str | None:
    """Digits of a call number when it can be a PBX extension (1-8 digits), else None."""
    text = (value or "").strip()
    if not text or not all(unicodedata.category(ch) == "Nd" for ch in text):
        return None
    key = normalize_call_number(text)
    return key if _EXTENSION_RE.fullmatch(key) else None


def clean_name(value: str | None) -> str | None:
    text = " ".join((value or "").split())[:_NAME_MAX]
    return text or None


async def sync(
    session: AsyncSession, tenant_id: UUID, items: Iterable[tuple[str, str | None]]
) -> SyncOutcome:
    """Upsert the PBX extension list; extensions missing from it are deactivated, not deleted."""
    wanted: dict[str, str | None] = {}
    for raw, name in items:
        key = extension_key(raw)
        if key is None:
            raise ApiError("invalid_request", "شمارهٔ داخلی نامعتبر است؛ فقط رقم، * و # مجاز است")
        wanted[key] = clean_name(name)
    if len(wanted) > MAX_SYNC_EXTENSIONS:
        raise ApiError("invalid_request", "تعداد داخلی‌ها بیش از حد مجاز است؛ لیست را کوتاه کنید")
    existing = {
        row.extension: row
        for row in (
            await session.execute(select(PbxExtension).where(PbxExtension.tenant_id == tenant_id))
        )
        .scalars()
        .all()
    }
    now = datetime.now(UTC)
    created = updated = 0
    for key, name in wanted.items():
        row = existing.get(key)
        if row is None:
            created += 1
        elif row.pbx_name != name or not row.active:
            updated += 1
        if row is None:
            statement = pg_insert(PbxExtension).values(
                tenant_id=tenant_id, extension=key, pbx_name=name, active=True, synced_at=now
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="pbx_extensions_tenant_extension_key",
                    set_={"pbx_name": name, "active": True, "synced_at": now, "updated_at": now},
                )
            )
        else:
            row.pbx_name = name
            row.active = True
            row.synced_at = now
            row.updated_at = now
    stale = [key for key, row in existing.items() if key not in wanted and row.active]
    for key in stale:
        existing[key].active = False
        existing[key].updated_at = now
    await session.flush()
    await reclassify_internal(session, tenant_id)
    return SyncOutcome(created=created, updated=updated, deactivated=len(stale))


async def known_extensions(session: AsyncSession, tenant_id: UUID) -> set[str]:
    rows = await session.execute(
        select(PbxExtension.extension).where(
            PbxExtension.tenant_id == tenant_id, PbxExtension.active.is_(True)
        )
    )
    return set(rows.scalars().all())


async def internal_direction_fixup(
    session: AsyncSession,
    tenant_id: UUID,
    caller: str | None,
    dialed: str | None,
    direction: str | None,
    agent_extension: str | None,
) -> tuple[str | None, str | None]:
    """Return (direction, agent_extension): a call between two known extensions is internal."""
    caller_key = extension_key(caller)
    dialed_key = extension_key(dialed)
    if caller_key is None or dialed_key is None:
        return direction, agent_extension
    known = await known_extensions(session, tenant_id)
    if caller_key in known and dialed_key in known:
        return "internal", agent_extension or dialed_key
    return direction, agent_extension


def is_internal(direction: str | None) -> bool:
    return direction == "internal"


async def reclassify_internal(session: AsyncSession, tenant_id: UUID, *, days: int = 30) -> int:
    """Mark recent calls between two active extensions as internal; returns rows changed.

    Run after every extension sync so calls ingested before the list was complete are fixed.
    """
    known = await known_extensions(session, tenant_id)
    if len(known) < 2:
        return 0
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await session.execute(
            select(Call.id, Call.caller_number, Call.dialed_number, Call.agent_extension).where(
                Call.tenant_id == tenant_id,
                Call.started_at >= since,
                or_(Call.direction.is_(None), Call.direction != "internal"),
            )
        )
    ).all()
    changed = 0
    for call_id, caller, dialed, agent in rows:
        caller_key = extension_key(caller)
        dialed_key = extension_key(dialed)
        if caller_key in known and dialed_key in known:
            await session.execute(
                update(Call)
                .where(Call.id == call_id)
                .values(direction="internal", agent_extension=agent or dialed_key)
            )
            changed += 1
    return changed


async def peer_labels(
    session: AsyncSession, tenant_id: UUID, caller: str | None, dialed: str | None
) -> dict[str, tuple[str | None, str | None]]:
    """Caller/callee of an internal call as (extension, display name)."""
    labels = await labels_for(session, tenant_id, [caller, dialed])
    return {
        "caller": (extension_key(caller), label_for(labels, caller)),
        "callee": (extension_key(dialed), label_for(labels, dialed)),
    }


async def labels_for(
    session: AsyncSession, tenant_id: UUID, numbers: Iterable[str | None]
) -> dict[str, str]:
    """Map extension -> display label: linked contact, else linked operator, else PBX name."""
    keys = {key for key in (extension_key(number) for number in numbers) if key is not None}
    if not keys:
        return {}
    rows = await session.execute(
        select(PbxExtension.extension, PbxExtension.pbx_name, Contact.name, User.display_name)
        .outerjoin(Contact, Contact.id == PbxExtension.contact_id)
        .outerjoin(User, User.id == PbxExtension.user_id)
        .where(PbxExtension.tenant_id == tenant_id, PbxExtension.extension.in_(keys))
    )
    labels: dict[str, str] = {}
    for extension, pbx_name, contact_name, display_name in rows.all():
        label = contact_name or display_name or pbx_name
        if label:
            labels[extension] = label
    return labels


def label_for(labels: Mapping[str, str], number: str | None) -> str | None:
    key = extension_key(number)
    return labels.get(key) if key is not None else None


async def assign(
    session: AsyncSession,
    tenant_id: UUID,
    row: PbxExtension,
    *,
    contact_id: UUID | None,
    user_id: UUID | None,
    set_contact: bool,
    set_user: bool,
) -> PbxExtension:
    """Link/unlink a contact and an operator; keeps `users.extension` in step."""
    now = datetime.now(UTC)
    if set_contact:
        if contact_id is not None:
            contact = (
                await session.execute(
                    select(Contact.id).where(
                        Contact.id == contact_id, Contact.tenant_id == tenant_id
                    )
                )
            ).first()
            if contact is None:
                raise ApiError("not_found", "مخاطب پیدا نشد؛ فهرست دفترچه تلفن را تازه کنید")
        row.contact_id = contact_id
    if set_user:
        if row.user_id is not None and row.user_id != user_id:
            await session.execute(
                update(User)
                .where(User.id == row.user_id, User.extension == row.extension)
                .values(extension=None)
            )
        if user_id is not None:
            operator = (
                await session.execute(
                    select(User).where(
                        User.id == user_id, User.tenant_id == tenant_id, User.role == "operator"
                    )
                )
            ).scalar_one_or_none()
            if operator is None:
                raise ApiError(
                    "not_found", "اپراتور پیدا نشد؛ فقط کاربر با نقش اپراتور قابل انتخاب است"
                )
            taken = (
                await session.execute(
                    select(PbxExtension.extension).where(
                        PbxExtension.tenant_id == tenant_id,
                        PbxExtension.user_id == user_id,
                        PbxExtension.id != row.id,
                    )
                )
            ).first()
            if taken is not None:
                raise ApiError(
                    "conflict",
                    f"این اپراتور قبلاً به داخلی {taken[0]} اختصاص دارد؛ ابتدا آن را آزاد کنید",
                )
            clash = (
                await session.execute(
                    select(User.id).where(
                        User.tenant_id == tenant_id,
                        User.extension == row.extension,
                        User.id != user_id,
                    )
                )
            ).first()
            if clash is not None:
                raise ApiError(
                    "conflict", "این داخلی در تنظیمات اپراتور دیگری ثبت شده؛ آن را آزاد کنید"
                )
            operator.extension = row.extension
        row.user_id = user_id
    row.updated_at = now
    await session.flush()
    return row
