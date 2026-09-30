from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.models import (
    IdentityProjectionOutbox,
    IdentityProjectionState,
    TenantDatabaseRegistry,
    User,
)


def _user_payload(user: User) -> dict[str, str | None]:
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "password_hash": user.password_hash,
        "role": user.role,
        "mobile_number": user.mobile_number,
        "extension": user.extension,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def stage_user_projection(
    session: AsyncSession, user: User, *, operation: str = "upsert"
) -> IdentityProjectionOutbox:
    now = datetime.now(UTC)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"identity:{user.tenant_id}:{user.id}"},
    )
    previous_version = int(
        (
            await session.execute(
                select(func.coalesce(func.max(IdentityProjectionOutbox.version), 0)).where(
                    IdentityProjectionOutbox.tenant_id == user.tenant_id,
                    IdentityProjectionOutbox.user_id == user.id,
                )
            )
        ).scalar_one()
    )
    version = max(int(now.timestamp() * 1_000_000), previous_version + 1)
    row = IdentityProjectionOutbox(
        tenant_id=user.tenant_id,
        user_id=user.id,
        operation=operation,
        version=version,
        payload=_user_payload(user),
    )
    session.add(row)
    await session.flush()
    return row


async def _apply(row: IdentityProjectionOutbox) -> None:
    async with session_scope(row.tenant_id) as target:
        state = await target.get(
            IdentityProjectionState,
            {"tenant_id": row.tenant_id, "user_id": row.user_id},
            with_for_update=True,
        )
        if state is not None and state.version >= row.version:
            return
        if row.operation == "delete":
            await target.execute(
                update(User)
                .where(User.id == row.user_id, User.tenant_id == row.tenant_id)
                .values(
                    role="viewer",
                    mobile_number=None,
                    extension=None,
                    display_name=None,
                )
            )
        else:
            payload = dict(row.payload)
            payload["id"] = UUID(str(payload["id"]))
            payload["tenant_id"] = UUID(str(payload["tenant_id"]))
            created_at = payload.get("created_at")
            if created_at:
                payload["created_at"] = datetime.fromisoformat(str(created_at))
            statement = pg_insert(User).values(**payload)
            await target.execute(
                statement.on_conflict_do_update(
                    index_elements=[User.id],
                    set_={
                        "email": statement.excluded.email,
                        "password_hash": statement.excluded.password_hash,
                        "role": statement.excluded.role,
                        "mobile_number": statement.excluded.mobile_number,
                        "extension": statement.excluded.extension,
                        "display_name": statement.excluded.display_name,
                    },
                )
            )
        if state is None:
            target.add(
                IdentityProjectionState(
                    tenant_id=row.tenant_id,
                    user_id=row.user_id,
                    version=row.version,
                )
            )
        else:
            state.version = row.version
            state.applied_at = datetime.now(UTC)


async def dispatch_next() -> str:
    async with session_scope(None, staff=True) as control:
        row = (
            await control.execute(
                select(IdentityProjectionOutbox)
                .join(
                    TenantDatabaseRegistry,
                    TenantDatabaseRegistry.tenant_id == IdentityProjectionOutbox.tenant_id,
                )
                .where(
                    IdentityProjectionOutbox.applied_at.is_(None),
                    IdentityProjectionOutbox.available_at <= datetime.now(UTC),
                    TenantDatabaseRegistry.status == "ready",
                )
                .order_by(IdentityProjectionOutbox.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return "idle"
        row_id = row.id
        tenant_id = row.tenant_id
        user_id = row.user_id
        operation = row.operation
        payload = dict(row.payload)
        version = row.version

    detached = IdentityProjectionOutbox(
        id=row_id,
        tenant_id=tenant_id,
        user_id=user_id,
        operation=operation,
        payload=payload,
        version=version,
    )
    try:
        await _apply(detached)
    except Exception as exc:
        async with session_scope(None, staff=True) as control:
            failed = await control.get(IdentityProjectionOutbox, row_id, with_for_update=True)
            if failed is not None:
                failed.attempt += 1
                failed.error_detail = str(exc)[:4000]
                failed.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(2 ** min(failed.attempt, 10), 900)
                )
        raise

    async with session_scope(None, staff=True) as control:
        applied = await control.get(IdentityProjectionOutbox, row_id, with_for_update=True)
        if applied is not None:
            applied.applied_at = datetime.now(UTC)
            applied.error_detail = None
    return "projected"
