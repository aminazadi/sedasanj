from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import StaffSession, SuperAdminDep, client_ip
from app.errors import ApiError
from app.models import TenantBackup, TenantDatabaseRegistry, TenantRestore
from app.routers.admin import _verify_sensitive_staff_action
from app.services import audit
from app.services.tenant_restores import ACTIVE_STATUSES, restore_error_info

router = APIRouter(prefix="/v1/admin", tags=["tenant-restores"])


class RestoreRequest(BaseModel):
    backup_id: UUID
    current_password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


class ApplyRequest(BaseModel):
    # The admin must type the live database name; a stray click cannot replace a database.
    confirm_database_name: str = Field(min_length=1, max_length=63)
    current_password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


def _restore_out(row: TenantRestore, live_database: str | None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "backup_id": str(row.backup_id) if row.backup_id else None,
        "status": row.status,
        "live_database": live_database,
        "previous_database": row.previous_database,
        "verification": row.verification,
        "error_info": (
            {**(restore_error_info(row.error_code) or {}), "detail": row.error_detail or ""}
            if row.error_code
            else None
        ),
        "created_at": row.created_at,
        "applied_at": row.applied_at,
    }


@router.get("/tenants/{tenant_id}/restore-options")
async def restore_options(
    tenant_id: UUID, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    registry = await session.get(TenantDatabaseRegistry, tenant_id)
    now = datetime.now(UTC)
    backups = (
        (
            await session.execute(
                select(TenantBackup)
                .where(
                    TenantBackup.tenant_id == tenant_id,
                    TenantBackup.status == "succeeded",
                    TenantBackup.expires_at > now,
                )
                .order_by(TenantBackup.completed_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    restores = (
        (
            await session.execute(
                select(TenantRestore)
                .where(TenantRestore.tenant_id == tenant_id)
                .order_by(TenantRestore.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    live = registry.database_name if registry else None
    return {
        "database_name": live,
        "database_ready": bool(registry and registry.status == "ready"),
        "backups": [
            {
                "id": str(row.id),
                "completed_at": row.completed_at,
                "size_bytes": row.size_bytes,
                "schema_revision": row.schema_revision,
            }
            for row in backups
        ],
        "restores": [_restore_out(row, live) for row in restores],
    }


@router.post("/tenants/{tenant_id}/restores", status_code=202)
async def request_restore(
    tenant_id: UUID,
    payload: RestoreRequest,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, str]:
    await _verify_sensitive_staff_action(
        session, staff, payload.current_password, payload.totp_code
    )
    registry = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
    if registry is None or registry.status != "ready":
        raise ApiError("invalid_request", "دیتابیس این سازمان آماده نیست.")
    backup = await session.get(TenantBackup, payload.backup_id)
    if (
        backup is None
        or backup.tenant_id != tenant_id
        or backup.status != "succeeded"
        or backup.expires_at is None
        or backup.expires_at <= datetime.now(UTC)
    ):
        raise ApiError("invalid_request", "بک‌آپ انتخاب‌شده معتبر یا منقضی‌نشده نیست.")
    active = (
        await session.execute(
            select(TenantRestore.id)
            .where(TenantRestore.tenant_id == tenant_id, TenantRestore.status.in_(ACTIVE_STATUSES))
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        raise ApiError("invalid_request", "یک بازیابی دیگر برای این سازمان در جریان است.")
    row = TenantRestore(tenant_id=tenant_id, backup_id=backup.id, requested_by=staff.id)
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=tenant_id,
        action="tenant_database.restore_requested",
        payload={"restore_id": str(row.id), "backup_id": str(backup.id)},
        ip=client_ip(request),
    )
    return {"id": str(row.id), "status": row.status}


@router.post("/tenant-restores/{restore_id}/apply", status_code=202)
async def apply_restore(
    restore_id: UUID,
    payload: ApplyRequest,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, str]:
    await _verify_sensitive_staff_action(
        session, staff, payload.current_password, payload.totp_code
    )
    row = await session.get(TenantRestore, restore_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "restore not found")
    registry = await session.get(TenantDatabaseRegistry, row.tenant_id)
    if row.status != "staged" or registry is None:
        raise ApiError("invalid_request", "این بازیابی هنوز آمادهٔ جایگزینی نیست.")
    if payload.confirm_database_name != registry.database_name:
        raise ApiError("invalid_request", "نام دیتابیس تأیید‌شده با دیتابیس سازمان یکی نیست.")
    row.status = "apply_requested"
    row.applied_by = staff.id
    row.error_code = None
    row.error_detail = None
    row.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=row.tenant_id,
        action="tenant_database.restore_apply_requested",
        payload={"restore_id": str(row.id)},
        ip=client_ip(request),
    )
    return {"id": str(row.id), "status": row.status}


@router.post("/tenant-restores/{restore_id}/cancel", status_code=202)
async def cancel_restore(
    restore_id: UUID, request: Request, staff: SuperAdminDep, session: StaffSession
) -> dict[str, str]:
    row = await session.get(TenantRestore, restore_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "restore not found")
    if row.status not in ("requested", "staging", "staged"):
        raise ApiError("invalid_request", "این بازیابی در این مرحله قابل لغو نیست.")
    row.status = "cancelled"
    row.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=row.tenant_id,
        action="tenant_database.restore_cancelled",
        payload={"restore_id": str(row.id)},
        ip=client_ip(request),
    )
    return {"id": str(row.id), "status": row.status}
