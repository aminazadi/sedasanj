from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.config import get_settings
from app.db import control_session_scope
from app.models import TenantBackup, TenantDatabaseRegistry
from app.services.storage import get_storage

_MAGIC = b"CBIBACKUP1"


def _encrypt_file(source: Path, target: Path, secret: str) -> tuple[str, int]:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = hashlib.sha256(secret.encode("utf-8")).digest()
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as src, target.open("wb") as dst:
        header = _MAGIC + nonce
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


async def _dump(database_name: str, destination: Path) -> None:
    from app.services.tenant_provisioning import _admin_url

    url = _admin_url(database_name)
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    command = ["pg_dump", "--format=custom", "--no-owner", "--no-acl"]
    if url.host:
        command.extend(["--host", url.host])
    if url.port:
        command.extend(["--port", str(url.port)])
    if url.username:
        command.extend(["--username", url.username])
    command.extend(["--file", str(destination), database_name])
    process = await asyncio.create_subprocess_exec(
        *command,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        detail = (stderr or stdout).decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"tenant backup failed: {detail}")


async def backup_next_due() -> str:
    settings = get_settings()
    if not settings.tenant_backup_enabled:
        return "disabled"
    cutoff = datetime.now(UTC) - timedelta(hours=settings.tenant_backup_interval_hours)
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
        registry = (
            await control.execute(
                select(TenantDatabaseRegistry)
                .outerjoin(latest, latest.c.tenant_id == TenantDatabaseRegistry.tenant_id)
                .where(
                    TenantDatabaseRegistry.status == "ready",
                    (latest.c.last_completed.is_(None) | (latest.c.last_completed < cutoff)),
                )
                .order_by(latest.c.last_completed.asc().nullsfirst())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if registry is None:
            return "idle"
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

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    object_key = f"tenant-backups/{tenant_id}/{timestamp}-{backup_id}.dump.enc"
    try:
        with tempfile.TemporaryDirectory(prefix="cbi-tenant-backup-") as directory:
            dump_path = Path(directory) / "tenant.dump"
            encrypted_path = Path(directory) / "tenant.dump.enc"
            await _dump(database_name, dump_path)
            if not settings.tenant_database_master_key:
                raise RuntimeError("tenant database master key is not configured")
            checksum, size = await asyncio.to_thread(
                _encrypt_file,
                dump_path,
                encrypted_path,
                settings.tenant_database_master_key,
            )
            storage = get_storage()
            await storage.ensure_bucket()
            await storage.put_path(
                object_key,
                encrypted_path,
                content_type="application/octet-stream",
            )
    except Exception as exc:
        async with control_session_scope() as control:
            row = await control.get(TenantBackup, backup_id, with_for_update=True)
            if row is not None:
                row.status = "failed"
                row.error_detail = str(exc)[:4000]
                row.completed_at = datetime.now(UTC)
        raise

    async with control_session_scope() as control:
        row = await control.get(TenantBackup, backup_id, with_for_update=True)
        if row is not None:
            row.status = "succeeded"
            row.object_key = object_key
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
            await control.execute(
                select(TenantBackup)
                .where(
                    TenantBackup.status == "succeeded",
                    TenantBackup.expires_at.is_not(None),
                    TenantBackup.expires_at < now,
                )
                .with_for_update(skip_locked=True)
                .limit(20)
            )
        ).scalars().all()
        targets = [(row.id, row.object_key) for row in rows if row.object_key]
    storage = get_storage()
    removed = 0
    for backup_id, object_key in targets:
        await storage.delete(object_key)
        async with control_session_scope() as control:
            row = await control.get(TenantBackup, backup_id, with_for_update=True)
            if row is not None:
                row.status = "expired"
                removed += 1
    return removed
