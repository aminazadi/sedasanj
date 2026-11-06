from __future__ import annotations

import asyncio
import hashlib
import hmac
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
    process = await asyncio.create_subprocess_exec(
        *command,
        "--dbname",
        database_name,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
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
            raise tenant_backup_format.InvalidBackup("pg_dump failed; check database access")
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


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
                    latest.c.last_completed.asc().nullsfirst(), TenantDatabaseRegistry.tenant_id
                )
                .with_for_update(of=TenantDatabaseRegistry, skip_locked=True)
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
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        object_key = f"tenant-backups/{tenant_id}/{timestamp}-{backup_id}.{suffix}"
        backup.object_key = object_key

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
    except (Exception, asyncio.CancelledError):
        async with control_session_scope() as control:
            row = await control.get(TenantBackup, backup_id, with_for_update=True)
            if row is not None:
                row.status = "failed"
                row.error_detail = "tenant_backup_failed"
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
