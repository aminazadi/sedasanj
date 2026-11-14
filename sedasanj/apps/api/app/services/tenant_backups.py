from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.config import get_settings
from app.db import control_session_scope
from app.models import TenantBackup, TenantDatabaseRegistry
from app.services import tenant_backup_format
from app.services.storage import get_storage
from app.services.tenant_db_metrics import backup_failures
from app.services.tenant_provisioning import sanitize_error_detail

logger = logging.getLogger(__name__)

# Stable codes for the admin page: code -> (Persian message, Persian next action).
BACKUP_ERRORS: dict[str, tuple[str, str]] = {
    "TENANT_BACKUP_KEY_MISSING": (
        "کلید بازیابی بک‌آپ تنظیم نشده است.",
        "TENANT_DATABASE_MASTER_KEY را در worker-tenant-backup تنظیم و سرویس را راه‌اندازی "
        "مجدد کنید.",
    ),
    "TENANT_BACKUP_DUMP_FAILED": (
        "pg_dump نتوانست از دیتابیس سازمان نسخه بگیرد.",
        "دسترسی PROVISIONER_DATABASE_URL و سازگاری نسخهٔ pg_dump با سرور را بررسی کنید؛ "
        "جزئیات فنی همین‌جا آمده است.",
    ),
    "TENANT_BACKUP_DUMP_INVALID": (
        "فایل نسخهٔ پشتیبان ساخته شد ولی pg_restore آن را نپذیرفت.",
        "دوباره پشتیبان‌گیری فوری بزنید؛ اگر تکرار شد نسخهٔ pg_dump و pg_restore را بررسی کنید.",
    ),
    "TENANT_BACKUP_TOO_LARGE": (
        "حجم نسخهٔ پشتیبان از سقف مجاز بیشتر است.",
        "TENANT_BACKUP_MAX_BYTES را متناسب با حجم دیتابیس افزایش دهید.",
    ),
    "TENANT_BACKUP_UPLOAD_FAILED": (
        "ارسال نسخهٔ پشتیبان به استوریج یا تأیید آن ناموفق بود.",
        "دسترسی و فضای استوریج (MinIO) را بررسی کنید و پشتیبان‌گیری فوری بزنید.",
    ),
    "TENANT_BACKUP_UNKNOWN": (
        "پشتیبان‌گیری با خطای ناشناخته متوقف شد.",
        "گزارش worker-tenant-backup را بررسی و پشتیبان‌گیری فوری بزنید.",
    ),
}


def classify_backup_error(exc: BaseException, phase: str) -> tuple[str, str]:
    """Return ``(code, sanitized detail)``; ``phase`` is ``dump`` or ``upload``."""
    raw = str(exc)
    detail = sanitize_error_detail(raw)
    lowered = raw.lower()
    if "recovery key" in lowered:
        return "TENANT_BACKUP_KEY_MISSING", detail
    if "size limit" in lowered:
        return "TENANT_BACKUP_TOO_LARGE", detail
    if "pg_dump failed" in lowered:
        return "TENANT_BACKUP_DUMP_FAILED", detail
    if "pg_restore rejected" in lowered:
        return "TENANT_BACKUP_DUMP_INVALID", detail
    if "checksum differs" in lowered or phase == "upload":
        return "TENANT_BACKUP_UPLOAD_FAILED", detail
    return "TENANT_BACKUP_UNKNOWN", detail


def backup_error_info(code: str | None) -> dict[str, str] | None:
    if not code:
        return None
    message, action = BACKUP_ERRORS.get(code, BACKUP_ERRORS["TENANT_BACKUP_UNKNOWN"])
    return {"code": code, "message": message, "action": action}


def _encrypt_file(source: Path, target: Path, secret: str) -> tuple[str, int]:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = hashlib.sha256(secret.encode("utf-8")).digest()
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as src, target.open("wb") as dst:
        header = tenant_backup_format.LEGACY_MAGIC + nonce
        dst.write(header)
        digest.update(header)
        size += len(header)
        while block := src.read(1024 * 1024):
            encrypted = encryptor.update(block)
            dst.write(encrypted)
            digest.update(encrypted)
            size += len(encrypted)
        final = encryptor.finalize()
        dst.write(final)
        digest.update(final)
        size += len(final)
        dst.write(encryptor.tag)
        digest.update(encryptor.tag)
        size += len(encryptor.tag)
    return digest.hexdigest(), size


def pg_connection_args(database_name: str) -> tuple[list[str], dict[str, str]]:
    from app.services.tenant_provisioning import _admin_url

    url = _admin_url(database_name)
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    command: list[str] = []
    if url.host:
        command.extend(["--host", url.host])
    if url.port:
        command.extend(["--port", str(url.port)])
    if url.username:
        command.extend(["--username", url.username])
    return command, env


async def _dump(database_name: str, destination: Path, limit: int, *, modern: bool) -> None:
    connection, env = pg_connection_args(database_name)
    command = ["pg_dump", "--format=custom", "--no-owner", "--no-acl", *connection]
    if modern:
        command.append("--compress=0")
    stderr_log = tempfile.TemporaryFile()  # noqa: SIM115 - closed in the finally block below
    process = await asyncio.create_subprocess_exec(
        *command,
        "--dbname",
        database_name,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=stderr_log,
    )
    assert process.stdout is not None
    try:
        with destination.open("xb") as output:
            while block := await process.stdout.read(tenant_backup_format.BLOCK):
                limit -= len(block)
                if limit < 0:
                    raise tenant_backup_format.InvalidBackup("backup exceeds the size limit")
                output.write(block)
        if await process.wait() or not destination.stat().st_size:
            stderr_log.seek(0)
            reason = stderr_log.read(4000).decode("utf-8", errors="replace")
            raise tenant_backup_format.InvalidBackup(
                f"pg_dump failed; check database access: {reason}"
            )
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        stderr_log.close()


async def verify_dump(path: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        "pg_restore",
        "--list",
        str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if await process.wait():
        raise tenant_backup_format.InvalidBackup("pg_restore rejected the dump")


async def backup_next_due() -> str:
    settings = get_settings()
    if not settings.tenant_backup_enabled:
        return "disabled"
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=settings.tenant_backup_interval_hours)
    modern = settings.tenant_backup_write_v2
    suffix = "gzip" if modern else "dump.enc"
    recent_attempt = (
        select(TenantBackup.id)
        .where(
            TenantBackup.tenant_id == TenantDatabaseRegistry.tenant_id,
            (
                (TenantBackup.status == "running")
                & (TenantBackup.started_at > now - timedelta(hours=3))
            )
            | (TenantBackup.started_at > now - timedelta(minutes=10)),
        )
        .exists()
    )
    latest = (
        select(
            TenantBackup.tenant_id,
            func.max(TenantBackup.completed_at).label("last_completed"),
        )
        .where(TenantBackup.status == "succeeded")
        .group_by(TenantBackup.tenant_id)
        .subquery()
    )
    async with control_session_scope() as control:
        requested = (
            await control.execute(
                select(TenantBackup)
                .join(
                    TenantDatabaseRegistry,
                    TenantDatabaseRegistry.tenant_id == TenantBackup.tenant_id,
                )
                .where(TenantBackup.status == "requested", TenantDatabaseRegistry.status == "ready")
                .order_by(TenantBackup.started_at)
                .with_for_update(of=TenantBackup, skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        registry = (
            await control.get(TenantDatabaseRegistry, requested.tenant_id)
            if requested is not None
            else None
        )
        if registry is None:
            registry = (
                await control.execute(
                    select(TenantDatabaseRegistry)
                    .outerjoin(latest, latest.c.tenant_id == TenantDatabaseRegistry.tenant_id)
                    .where(
                        TenantDatabaseRegistry.status == "ready",
                        (latest.c.last_completed.is_(None) | (latest.c.last_completed < cutoff)),
                        ~recent_attempt,
                    )
                    .order_by(
                        latest.c.last_completed.asc().nullsfirst(),
                        TenantDatabaseRegistry.tenant_id,
                    )
                    .with_for_update(of=TenantDatabaseRegistry, skip_locked=True)
                    .limit(1)
                )
            ).scalar_one_or_none()
        if registry is None:
            return "idle"
        if requested is not None:
            backup = requested
            backup.status = "running"
            backup.started_at = now
            backup.schema_revision = registry.schema_revision
            backup.error_code = None
            backup.error_detail = None
        else:
            backup = TenantBackup(
                tenant_id=registry.tenant_id,
                status="running",
                schema_revision=registry.schema_revision,
            )
            control.add(backup)
        await control.flush()
        backup_id = backup.id
        tenant_id = registry.tenant_id
        database_name = registry.database_name
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        object_key = f"tenant-backups/{tenant_id}/{timestamp}-{backup_id}.{suffix}"
        backup.object_key = object_key

    phase = "dump"
    try:
        with tempfile.TemporaryDirectory(prefix="cbi-tenant-backup-") as directory:
            dump_path = Path(directory) / "tenant.dump"
            encrypted_path = Path(directory) / f"tenant.{suffix}"
            if not settings.tenant_database_master_key:
                raise tenant_backup_format.InvalidBackup("configure the tenant backup recovery key")
            await _dump(database_name, dump_path, settings.tenant_backup_max_bytes, modern=modern)
            await verify_dump(dump_path)
            args = (dump_path, encrypted_path, settings.tenant_database_master_key)
            if modern:
                checksum, size = await asyncio.to_thread(
                    tenant_backup_format.seal, *args, settings.tenant_backup_max_bytes
                )
            else:
                checksum, size = await asyncio.to_thread(_encrypt_file, *args)
            phase = "upload"
            storage = get_storage()
            await storage.ensure_bucket()
            await storage.put_path(
                object_key,
                encrypted_path,
                content_type="application/gzip" if modern else "application/octet-stream",
            )
            actual = hashlib.sha256()
            stored_bytes = 0
            async for block in storage.iter_chunks(object_key):
                stored_bytes += len(block)
                if stored_bytes > size:
                    break
                actual.update(block)
            if stored_bytes != size or not hmac.compare_digest(actual.hexdigest(), checksum):
                raise tenant_backup_format.InvalidBackup("uploaded backup checksum differs")
    except (Exception, asyncio.CancelledError) as exc:
        code, detail = classify_backup_error(exc, phase)
        backup_failures.labels(code=code).inc()
        logger.error(
            "tenant backup failed tenant_id=%s backup_id=%s code=%s detail=%s",
            tenant_id,
            backup_id,
            code,
            detail,
        )
        async with control_session_scope() as control:
            row = await control.get(TenantBackup, backup_id, with_for_update=True)
            if row is not None:
                row.status = "failed"
                row.error_code = code
                row.error_detail = detail
                row.completed_at = datetime.now(UTC)
        raise

    async with control_session_scope() as control:
        row = await control.get(TenantBackup, backup_id, with_for_update=True)
        if row is not None:
            row.status = "succeeded"
            row.checksum_sha256 = checksum
            row.size_bytes = size
            row.completed_at = datetime.now(UTC)
            row.expires_at = datetime.now(UTC) + timedelta(
                days=settings.tenant_backup_retention_days
            )
    return "backed_up"


async def purge_expired() -> int:
    now = datetime.now(UTC)
    async with control_session_scope() as control:
        rows = (
            (
                await control.execute(
                    select(TenantBackup)
                    .where(
                        TenantBackup.object_key.is_not(None),
                        ((TenantBackup.status == "succeeded") & (TenantBackup.expires_at < now))
                        | (TenantBackup.status == "failed")
                        | (
                            (TenantBackup.status == "running")
                            & (TenantBackup.started_at < now - timedelta(hours=3))
                        ),
                    )
                    .order_by(TenantBackup.started_at)
                    .with_for_update(skip_locked=True)
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        targets = [(row.id, row.object_key) for row in rows if row.object_key]
    storage = get_storage()
    removed = 0
    for backup_id, object_key in targets:
        await storage.delete(object_key)
        async with control_session_scope() as control:
            row = await control.get(TenantBackup, backup_id, with_for_update=True)
            if row is not None:
                if row.status == "succeeded":
                    row.status = "expired"
                else:
                    row.status = "failed"
                    row.error_detail = "tenant_backup_failed"
                    row.completed_at = row.completed_at or now
                row.object_key = None
                removed += 1
    return removed
