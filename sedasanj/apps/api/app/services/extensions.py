"""PBX extensions synced from the FreePBX module.

An extension can be linked to a phonebook contact and to an operator. The inventory is
the authority for new PBX operator assignments.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Contact, PbxExtension, Tenant, User

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
    key = "".join(str(unicodedata.decimal(character)) for character in text)
    return key if _EXTENSION_RE.fullmatch(key) else None


def clean_name(value: str | None) -> str | None:
    text = " ".join((value or "").split())[:_NAME_MAX]
    return text or None


async def lock_inventory(session: AsyncSession, tenant_id: UUID, *, shared: bool = False) -> None:
    await session.execute(
        text(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(:key, 0))"
            if shared
            else "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"
        ),
        {"key": f"pbx-inventory:{tenant_id}"},
    )


async def sync(
    session: AsyncSession,
    tenant_id: UUID,
    items: Iterable[tuple[str, str | None]],
    host_uuid: UUID | None = None,
) -> SyncOutcome:
    """Upsert the PBX extension list; extensions missing from it are deactivated, not deleted."""
    wanted: dict[str, str | None] = {}
    for raw, name in items:
        key = extension_key(raw)
        if key is None:
            raise ApiError("invalid_request", "شمارهٔ داخلی نامعتبر است؛ یک تا هشت رقم وارد کنید")
        if key in wanted:
            raise ApiError("invalid_request", "فهرست داخلی تکراری است؛ فهرست FreePBX را بررسی کنید")
        wanted[key] = clean_name(name)
    if len(wanted) > MAX_SYNC_EXTENSIONS:
        raise ApiError("invalid_request", "تعداد داخلی‌ها بیش از حد مجاز است؛ لیست را کوتاه کنید")
    if not wanted:
        raise ApiError("invalid_request", "فهرست داخلی خالی است؛ تنظیمات FreePBX را بررسی کنید")
    await lock_inventory(session, tenant_id)
    tenant = await session.get(Tenant, tenant_id, populate_existing=True)
    if tenant is None:
        raise ApiError("not_found", "سازمان یافت نشد؛ اتصال FreePBX را بررسی کنید")
    if tenant.pbx_host_uuid is not None and tenant.pbx_host_uuid != host_uuid:
        raise ApiError(
            "pbx_source_conflict",
            "منبع همگام‌سازی متفاوت است؛ اتصال FreePBX را در تنظیمات بررسی کنید",
        )
    if host_uuid is not None:
        tenant.pbx_host_uuid = host_uuid
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
    await link_unique_operator_extensions(session, tenant_id)
    return SyncOutcome(created=created, updated=updated, deactivated=len(stale))


async def link_unique_operator_extensions(session: AsyncSession, tenant_id: UUID) -> None:
    rows = (
        await session.scalars(select(PbxExtension).where(PbxExtension.tenant_id == tenant_id))
    ).all()
    linked = {row.user_id for row in rows if row.user_id is not None}
    by_extension: dict[str, list[User]] = {}
    for user in (await session.scalars(select(User).where(User.tenant_id == tenant_id))).all():
        key = extension_key(user.extension)
        if key is not None:
            by_extension.setdefault(key, []).append(user)
    for row in rows:
        matches = by_extension.get(row.extension, [])
        if row.active and not row.owner_managed and row.user_id is None and len(matches) == 1:
            user = matches[0]
            if user.role == "operator" and user.id not in linked:
                row.user_id = user.id
                row.owner_linked_at = datetime.now(UTC)
                linked.add(user.id)
    await session.flush()


async def reconcile_operator(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, extension: str | None
) -> None:
    """Apply an explicit organization user edit to the PBX inventory."""
    key = extension_key(extension)
    rows = (
        await session.scalars(
            select(PbxExtension).where(
                PbxExtension.tenant_id == tenant_id,
                or_(PbxExtension.user_id == user_id, PbxExtension.extension == key),
            )
        )
    ).all()
    target = next((row for row in rows if row.extension == key and row.active), None)
    if target is not None and target.user_id not in (None, user_id):
        raise ApiError("conflict", "داخلی به اپراتور دیگری متصل است؛ ابتدا اتصال آن را آزاد کنید")
    now = datetime.now(UTC)
    for row in rows:
        if row is not target and row.user_id == user_id:
            row.user_id = None
            row.owner_linked_at = None
            row.owner_managed = True
            row.updated_at = now
    await session.flush()
    if target is not None and target.user_id != user_id:
        target.user_id = user_id
        target.owner_linked_at = now
        target.owner_managed = True
        target.updated_at = now
    await session.flush()


async def known_extensions(session: AsyncSession, tenant_id: UUID) -> set[str]:
    rows = await session.execute(
        select(PbxExtension.extension).where(
            PbxExtension.tenant_id == tenant_id, PbxExtension.active.is_(True)
        )
    )
    return set(rows.scalars().all())


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
            previous = await session.get(User, row.user_id)
            if (
                previous is not None
                and previous.tenant_id == tenant_id
                and extension_key(previous.extension) == row.extension
            ):
                previous.extension = None
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
            other_extensions = (
                await session.scalars(
                    select(User.extension).where(
                        User.tenant_id == tenant_id,
                        User.extension.is_not(None),
                        User.id != user_id,
                    )
                )
            ).all()
            if any(extension_key(value) == row.extension for value in other_extensions):
                raise ApiError(
                    "conflict", "این داخلی در تنظیمات اپراتور دیگری ثبت شده؛ آن را آزاد کنید"
                )
            operator.extension = row.extension
        if row.user_id != user_id:
            row.owner_linked_at = now if user_id is not None else None
        row.user_id = user_id
        row.owner_managed = True
    row.updated_at = now
    await session.flush()
    return row
