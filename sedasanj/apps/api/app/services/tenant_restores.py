"""Admin-driven restore of one tenant database from a verified backup.

Flow (each step is run by ``worker-tenant-backup``; the admin API only changes ``status``):

1. ``requested``  -> ``staging`` -> ``staged``: the backup is downloaded, checksum-verified,
   decrypted and restored into a scratch ``cbi_restore_<hex>`` database, the Apache AGE graph is
   repaired and identity, revision, graph and media references are verified.
2. ``apply_requested`` -> ``applying`` -> ``applied``: after an explicit admin confirmation the
   organization is made read-only, running jobs drain, the live database is renamed to
   ``<db>_pre<stamp>`` (kept for rollback) and the staged one takes its name. Grants are reapplied
   and the runtime role must pass identity and graph checks. Any failure after the rename swaps the
   databases back.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.db import control_session_scope, invalidate_tenant_engine
from app.models import Tenant, TenantDatabaseRegistry, TenantRestore
from app.services import audit, tenant_backup_format
from app.services.apache_age import assert_age_ready
from app.services.tenant_backup_restore import _stage_file, download
from app.services.tenant_db_metrics import restore_failures, restores_applied
from app.services.tenant_provisioning import (
    _admin_url,
    _checked_identifier,
    grant_database_access,
    grant_schema_access,
    sanitize_error_detail,
)
from app.services.tenant_secrets import decrypt_dsn

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("requested", "staging", "staged", "apply_requested", "applying")
STAGED_TTL = timedelta(hours=24)
_STAGING_NAME = re.compile(r"^cbi_restore_[0-9a-f]{32}$")
_SUMMARY_TABLES = ("users", "calls", "meetings", "contacts")

RESTORE_ERRORS: dict[str, tuple[str, str]] = {
    "TENANT_RESTORE_BACKUP_INVALID": (
        "فایل بک‌آپ معتبر نبود یا بازیابی آزمایشی آن رد شد.",
        "بک‌آپ دیگری انتخاب کنید یا پشتیبان‌گیری فوری بزنید؛ دلیل دقیق در جزئیات فنی است.",
    ),
    "TENANT_RESTORE_NOT_READY": (
        "دیتابیس این سازمان در حال حاضر آمادهٔ جایگزینی نیست.",
        "پس از پایان انتقال یا ارتقای دیتابیس سازمان دوباره درخواست دهید.",
    ),
    "TENANT_RESTORE_STAGING_MISSING": (
        "دیتابیس آزمایشی بازیابی دیگر وجود ندارد.",
        "بازیابی را لغو کنید و دوباره از ابتدا درخواست دهید.",
    ),
    "TENANT_RESTORE_DRAIN_TIMEOUT": (
        "کارهای در حال اجرای سازمان در مهلت تعیین‌شده تمام نشد؛ چیزی جایگزین نشد.",
        "پس از پایان یا توقف کارهای در حال اجرا دوباره «جایگزینی» را بزنید.",
    ),
    "TENANT_RESTORE_SWAP_FAILED": (
        "جایگزینی دیتابیس ناموفق بود و دیتابیس قبلی برگردانده شد.",
        "گزارش worker-tenant-backup را بررسی کنید و پس از رفع علت دوباره تلاش کنید.",
    ),
    "TENANT_RESTORE_VERIFY_FAILED": (
        "دیتابیس بازیابی‌شده بعد از جایگزینی تأیید نشد و دیتابیس قبلی برگردانده شد.",
        "بک‌آپ دیگری را امتحان کنید؛ دلیل دقیق در جزئیات فنی است.",
    ),
    "TENANT_RESTORE_UNKNOWN": (
        "بازیابی با خطای ناشناخته متوقف شد.",
        "گزارش worker-tenant-backup را بررسی و دوباره تلاش کنید.",
    ),
}


class TenantRestoreError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def classify_restore_error(exc: BaseException) -> tuple[str, str]:
    detail = sanitize_error_detail(str(exc))
    if isinstance(exc, TenantRestoreError):
        return exc.code, detail
    if isinstance(exc, tenant_backup_format.InvalidBackup):
        return "TENANT_RESTORE_BACKUP_INVALID", detail
    return "TENANT_RESTORE_UNKNOWN", detail


def restore_error_info(code: str | None) -> dict[str, str] | None:
    if not code:
        return None
    message, action = RESTORE_ERRORS.get(code, RESTORE_ERRORS["TENANT_RESTORE_UNKNOWN"])
    return {"code": code, "message": message, "action": action}


def _engine(database: str | None = None) -> AsyncEngine:
    return create_async_engine(
        _admin_url(database).render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )


async def _database_exists(engine: AsyncEngine, name: str) -> bool:
    async with engine.connect() as connection:
        return bool(
            (
                await connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
                )
            ).scalar_one_or_none()
        )


async def _summarize(database: str) -> dict[str, Any]:
    engine = _engine(database)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            counts: dict[str, int] = {}
            for table in _SUMMARY_TABLES:
                if await connection.scalar(text("SELECT to_regclass(:name)"), {"name": table}):
                    counts[table] = int(
                        await connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0
                    )
    finally:
        await engine.dispose()
    return {"schema_revision": revision, "counts": counts}


async def _drop_database(name: str) -> None:
    if not _STAGING_NAME.fullmatch(name):
        raise ValueError("refusing to drop a database that is not a staging restore")
    engine = _engine()
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    finally:
        await engine.dispose()


async def _mark(restore_id: UUID, **values: Any) -> None:
    async with control_session_scope() as session:
        row = await session.get(TenantRestore, restore_id, with_for_update=True)
        if row is not None:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(UTC)


async def stage_next() -> str:
    async with control_session_scope() as session:
        row = (
            await session.execute(
                select(TenantRestore)
                .where(TenantRestore.status == "requested")
                .order_by(TenantRestore.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return "idle"
        row.status = "staging"
        row.updated_at = datetime.now(UTC)
        restore_id, tenant_id, backup_id = row.id, row.tenant_id, row.backup_id
    staging = f"cbi_restore_{uuid.uuid4().hex}"
    try:
        if backup_id is None:
            raise tenant_backup_format.InvalidBackup("the selected backup no longer exists")
        with tempfile.TemporaryDirectory(prefix="cbi-tenant-restore-stage-") as directory:
            archive = Path(directory) / "backup"
            tenant, revision = await download(backup_id, archive)
            if tenant != tenant_id:
                raise tenant_backup_format.InvalidBackup("backup belongs to another organization")
            await _stage_file(archive, tenant, revision, staging)
        summary = await _summarize(staging)
    except Exception as exc:
        code, detail = classify_restore_error(exc)
        restore_failures.labels(code=code).inc()
        logger.error(
            "tenant restore staging failed restore_id=%s code=%s detail=%s",
            restore_id,
            code,
            detail,
        )
        await _mark(restore_id, status="failed", error_code=code, error_detail=detail)
        return "failed"
    async with control_session_scope() as session:
        row = await session.get(TenantRestore, restore_id, with_for_update=True)
        keep = row is not None and row.status == "staging"
        if row is not None and keep:
            row.status = "staged"
            row.staging_database = staging
            row.verification = summary
            row.updated_at = datetime.now(UTC)
    if not keep:  # cancelled while staging
        await _drop_database(staging)
        return "cancelled"
    return "staged"


async def _running_jobs(database: str, tenant_id: UUID) -> int:
    engine = create_async_engine(_admin_url(database).render_as_string(hide_password=False))
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT set_config('app.staff', 'on', true)"))
            return int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM jobs WHERE tenant_id = :tenant AND status = 'running'"
                    ),
                    {"tenant": tenant_id},
                )
                or 0
            )
    finally:
        await engine.dispose()


async def _swap(live: str, staging: str, previous: str) -> None:
    engine = _engine()
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"ALTER DATABASE {live} ALLOW_CONNECTIONS false"))
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": live},
            )
            await connection.execute(text(f"ALTER DATABASE {live} RENAME TO {previous}"))
            await connection.execute(text(f"ALTER DATABASE {staging} RENAME TO {live}"))
            await connection.execute(text(f"ALTER DATABASE {live} ALLOW_CONNECTIONS true"))
            await connection.execute(text(f"ALTER DATABASE {previous} ALLOW_CONNECTIONS true"))
    finally:
        await engine.dispose()


async def _undo_swap(live: str, staging: str, previous: str) -> None:
    """Put the previous database back under the live name, whatever step of _swap failed."""
    engine = _engine()
    try:
        if not await _database_exists(engine, previous):
            # _swap failed before the first rename: the live database is untouched.
            async with engine.connect() as connection:
                await connection.execute(text(f"ALTER DATABASE {live} ALLOW_CONNECTIONS true"))
            return
        async with engine.connect() as connection:
            if await _database_exists(engine, live):
                await connection.execute(text(f"ALTER DATABASE {live} ALLOW_CONNECTIONS false"))
                await connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": live},
                )
                await connection.execute(text(f"ALTER DATABASE {live} RENAME TO {staging}"))
                # Reopen it: the staged copy must stay usable so the admin can retry the apply.
                await connection.execute(text(f"ALTER DATABASE {staging} ALLOW_CONNECTIONS true"))
            await connection.execute(text(f"ALTER DATABASE {previous} RENAME TO {live}"))
            await connection.execute(text(f"ALTER DATABASE {live} ALLOW_CONNECTIONS true"))
    finally:
        await engine.dispose()


async def _prepare_live(live: str, role: str, tenant_id: UUID, encrypted_dsn: str) -> str:
    admin = _engine()
    try:
        async with admin.connect() as connection:
            await grant_database_access(connection, live, role)
    finally:
        await admin.dispose()
    target = create_async_engine(_admin_url(live).render_as_string(hide_password=False))
    try:
        async with target.begin() as connection:
            await grant_schema_access(connection, role)
    finally:
        await target.dispose()
    runtime = create_async_engine(decrypt_dsn(encrypted_dsn), pool_pre_ping=True)
    try:
        async with runtime.connect() as connection:
            identity = (
                await connection.execute(text("SELECT tenant_id FROM tenant_identity LIMIT 1"))
            ).scalar_one_or_none()
            if str(identity) != str(tenant_id):
                raise TenantRestoreError(
                    "TENANT_RESTORE_VERIFY_FAILED", "restored database belongs to another tenant"
                )
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            await assert_age_ready(connection)
    finally:
        await runtime.dispose()
    return str(revision)


async def apply_next() -> str:
    async with control_session_scope() as session:
        row = (
            await session.execute(
                select(TenantRestore)
                .where(TenantRestore.status == "apply_requested")
                .order_by(TenantRestore.updated_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return "idle"
        restore_id, tenant_id, staging = row.id, row.tenant_id, row.staging_database
        applied_by = row.applied_by
        row.status = "applying"
        row.updated_at = datetime.now(UTC)
    live = role = encrypted_dsn = ""
    previous_status = "active"
    swapped = False
    locked = False
    previous = ""
    try:
        async with control_session_scope() as session:
            registry = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
            tenant = await session.get(Tenant, tenant_id, with_for_update=True)
            if registry is None or tenant is None or registry.status != "ready":
                raise TenantRestoreError(
                    "TENANT_RESTORE_NOT_READY", "tenant database registry is not ready"
                )
            live, role, encrypted_dsn = (
                registry.database_name,
                registry.runtime_role,
                registry.encrypted_dsn,
            )
            previous_status = tenant.status
            registry.status = "maintenance"
            if tenant.status == "active":
                tenant.status = "maintenance_readonly"
            locked = True
            checkpoint = {"tenant_status": previous_status, "live_database": live}
        await _mark(restore_id, checkpoint=checkpoint)
        _checked_identifier(live)
        if not staging or not _STAGING_NAME.fullmatch(staging):
            raise TenantRestoreError("TENANT_RESTORE_STAGING_MISSING", "no staging database")
        probe = _engine()
        try:
            if not await _database_exists(probe, staging):
                raise TenantRestoreError("TENANT_RESTORE_STAGING_MISSING", "staging database gone")
        finally:
            await probe.dispose()
        await invalidate_tenant_engine(tenant_id)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + get_settings().tenant_migration_drain_seconds
        while await _running_jobs(live, tenant_id):
            if loop.time() >= deadline:
                raise TenantRestoreError("TENANT_RESTORE_DRAIN_TIMEOUT", "job drain timed out")
            await asyncio.sleep(2)
        previous = f"{live}_pre{datetime.now(UTC).strftime('%y%m%d%H%M%S')}"
        _checked_identifier(previous)
        try:
            await _swap(live, staging, previous)
            swapped = True
        except Exception as exc:
            raise TenantRestoreError("TENANT_RESTORE_SWAP_FAILED", str(exc)) from exc
        try:
            revision = await _prepare_live(live, role, tenant_id, encrypted_dsn)
        except TenantRestoreError:
            raise
        except Exception as exc:
            raise TenantRestoreError("TENANT_RESTORE_VERIFY_FAILED", str(exc)) from exc
    except Exception as exc:
        if swapped or previous:
            try:
                await _undo_swap(live, staging or "", previous)
            except Exception:
                logger.error(
                    "tenant restore could not swap back restore_id=%s live=%s previous=%s",
                    restore_id,
                    live,
                    previous,
                )
        code, detail = classify_restore_error(exc)
        restore_failures.labels(code=code).inc()
        logger.error(
            "tenant restore apply failed restore_id=%s code=%s detail=%s", restore_id, code, detail
        )
        async with control_session_scope() as session:
            registry = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
            tenant = await session.get(Tenant, tenant_id, with_for_update=True)
            if locked and registry is not None and registry.status == "maintenance":
                registry.status = "ready"
            if locked and tenant is not None and tenant.status == "maintenance_readonly":
                tenant.status = previous_status
        # The staged database is still intact after a swap-back, so the admin can retry apply.
        await _mark(
            restore_id,
            status="staged" if code != "TENANT_RESTORE_STAGING_MISSING" else "failed",
            error_code=code,
            error_detail=detail,
        )
        await invalidate_tenant_engine(tenant_id)
        return "failed"
    async with control_session_scope() as session:
        registry = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
        tenant = await session.get(Tenant, tenant_id, with_for_update=True)
        restore = await session.get(TenantRestore, restore_id, with_for_update=True)
        assert registry is not None and tenant is not None and restore is not None
        registry.status = "ready"
        registry.schema_revision = revision
        registry.last_health_at = datetime.now(UTC)
        if tenant.status == "maintenance_readonly":
            tenant.status = previous_status
        restore.status = "applied"
        restore.previous_database = previous
        restore.staging_database = None
        restore.error_code = None
        restore.error_detail = None
        restore.applied_at = datetime.now(UTC)
        restore.updated_at = datetime.now(UTC)
        await audit.record(
            session,
            actor_type="staff" if applied_by else "system",
            actor_id=applied_by,
            tenant_id=tenant_id,
            action="tenant_database.restore_applied",
            payload={"restore_id": str(restore_id), "previous_database": previous},
        )
    restores_applied.inc()
    await invalidate_tenant_engine(tenant_id)
    return "applied"


async def cleanup() -> int:
    """Drop staging databases of cancelled or failed restores and expire stale staged ones."""
    now = datetime.now(UTC)
    removed = 0
    async with control_session_scope() as session:
        stale = (
            (
                await session.execute(
                    select(TenantRestore)
                    .where(
                        TenantRestore.status == "staged",
                        TenantRestore.updated_at < now - STAGED_TTL,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        for row in stale:
            row.status = "cancelled"
            row.error_detail = "expired after 24 hours without being applied"
            row.updated_at = now
        rows = (
            await session.execute(
                select(TenantRestore.id, TenantRestore.staging_database)
                .where(
                    TenantRestore.status.in_(("cancelled", "failed")),
                    TenantRestore.staging_database.is_not(None),
                )
                .limit(20)
            )
        ).all()
    for restore_id, database in rows:
        try:
            await _drop_database(str(database))
        except Exception:
            logger.error("could not drop staging database restore_id=%s", restore_id)
            continue
        await _mark(restore_id, staging_database=None)
        removed += 1
    return removed


async def active_count() -> int:
    async with control_session_scope() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(TenantRestore)
                .where(TenantRestore.status.in_(ACTIVE_STATUSES))
            )
            or 0
        )
