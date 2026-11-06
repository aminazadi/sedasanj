from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import control_session_scope, dispose_engine
from app.models import TenantBackup
from app.services import audit, tenant_backup_format
from app.services.storage import get_storage
from app.services.tenant_backups import pg_connection_args, verify_dump
from app.services.tenant_provisioning import _admin_url

VERIFIED_RESTORE_ACTION = "tenant.backup.restore_verified"


async def download(backup_id: UUID, target: Path) -> tuple[UUID, str | None]:
    async with control_session_scope() as session:
        row = await session.get(TenantBackup, backup_id)
        if (
            not row
            or row.status != "succeeded"
            or not row.expires_at
            or row.expires_at <= datetime.now(UTC)
            or not row.object_key
            or not row.checksum_sha256
            or not row.size_bytes
        ):
            raise tenant_backup_format.InvalidBackup("select a successful, unexpired tenant backup")
        tenant, revision = row.tenant_id, row.schema_revision
        key, checksum, expected_size = row.object_key, row.checksum_sha256, row.size_bytes

    if not key.startswith(f"tenant-backups/{tenant}/"):
        raise tenant_backup_format.InvalidBackup("backup registry has an invalid object key")
    limit = tenant_backup_format.wire_limit(get_settings().tenant_backup_max_bytes)
    if expected_size > limit:
        raise tenant_backup_format.InvalidBackup("backup exceeds the configured size limit")
    digest = hashlib.sha256()
    total = 0
    handle = target.open("xb")
    try:
        with handle:
            async for block in get_storage().iter_chunks(key):
                total += len(block)
                if total > expected_size:
                    raise tenant_backup_format.InvalidBackup(
                        "backup size does not match the registry"
                    )
                digest.update(block)
                handle.write(block)
        if total != expected_size or not hmac.compare_digest(digest.hexdigest(), checksum):
            raise tenant_backup_format.InvalidBackup("backup checksum does not match the registry")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return tenant, revision


async def _verify_database(database: str, tenant: UUID, revision: str | None) -> None:
    storage = get_storage()
    engine = create_async_engine(_admin_url(database))
    try:
        async with engine.connect() as connection:
            identities = (
                await connection.scalars(text("SELECT tenant_id FROM tenant_identity"))
            ).all()
            actual_revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            if identities != [tenant] or (revision and actual_revision != revision):
                raise tenant_backup_format.InvalidBackup(
                    "restored database identity or revision differs"
                )
            rows = await connection.stream_scalars(
                text("""
                    SELECT object_key FROM audio_objects
                      WHERE deleted_at IS NULL AND (expires_at IS NULL OR expires_at > now())
                    UNION
                    SELECT storage_key FROM assistant_exports
                      WHERE deleted_at IS NULL AND expires_at > now()
                    """)
            )
            async for key in rows:
                if not await storage.exists(key):
                    raise tenant_backup_format.InvalidBackup(
                        "backup references missing media; restore the matching server snapshot"
                    )
    finally:
        await engine.dispose()


async def _run_pg(command: str, *arguments: str, database: str) -> None:
    connection, env = pg_connection_args(database)
    process = await asyncio.create_subprocess_exec(
        command,
        *connection,
        *arguments,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if await process.wait():
        raise tenant_backup_format.InvalidBackup(
            f"{command} failed; inspect the staging environment"
        )


async def _stage_file(archive: Path, tenant: UUID, revision: str | None, database: str) -> None:
    if not re.fullmatch(r"cbi_restore_[0-9a-f]{32}", database):
        raise tenant_backup_format.InvalidBackup(
            "choose a fresh cbi_restore_<32 lowercase hex> database"
        )
    settings = get_settings()
    secret = settings.tenant_database_master_key
    if not secret:
        raise tenant_backup_format.InvalidBackup("configure the tenant backup recovery key")
    with tempfile.TemporaryDirectory(prefix="cbi-tenant-restore-") as temporary:
        dump = Path(temporary) / "backup.dump"
        await asyncio.to_thread(
            tenant_backup_format.unseal, archive, dump, secret, settings.tenant_backup_max_bytes
        )
        await verify_dump(dump)
        await _run_pg("createdb", "--template=template0", database, database=database)
        try:
            await _run_pg(
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-acl",
                "--dbname",
                database,
                str(dump),
                database=database,
            )
            await _verify_database(database, tenant, revision)
        except BaseException:
            await _run_pg("dropdb", database, database=database)
            raise


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and restore a tenant backup to a fresh database"
    )
    parser.add_argument("id", type=UUID, help="backup ID, or expected tenant ID with --file")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--stage", metavar="DATABASE")
    action.add_argument("--download", type=Path, metavar="FILE")
    parser.add_argument("--file", type=Path, help="restore a previously downloaded backup")
    args = parser.parse_args()
    if args.file and not args.stage:
        parser.error("--file requires --stage")
    started = time.monotonic()
    try:
        if args.stage and args.file:
            tenant = args.id
            await _stage_file(args.file, args.id, None, args.stage)
        elif args.stage:
            with tempfile.TemporaryDirectory(prefix="cbi-tenant-download-") as temporary:
                archive = Path(temporary) / "backup"
                tenant, revision = await download(args.id, archive)
                await _stage_file(archive, tenant, revision, args.stage)
        else:
            with tempfile.TemporaryDirectory(dir=args.download.parent) as directory:
                artifact = Path(directory) / "backup"
                await download(args.id, artifact)
                with artifact.open("rb") as stream:
                    modern = stream.read(2) == b"\x1f\x8b"
                suffix = ".gzip" if modern else ".dump.enc"
                if not args.download.name.endswith(suffix):
                    raise tenant_backup_format.InvalidBackup(f"use the {suffix} file extension")
                os.link(artifact, args.download)
            print("Verified backup download saved")
            return
        async with control_session_scope() as session:
            await audit.record(
                session,
                actor_type="system",
                tenant_id=tenant,
                action=VERIFIED_RESTORE_ACTION,
                payload={"duration_seconds": round(time.monotonic() - started, 2)},
            )
        print(f"Verified staging database: {args.stage}")
    except (OSError, EOFError, tenant_backup_format.InvalidBackup) as exc:
        message = (
            str(exc)
            if isinstance(exc, tenant_backup_format.InvalidBackup)
            else "check the archive, destination and staging disk"
        )
        parser.exit(1, f"{message}\n")
    except Exception:
        parser.exit(1, "Backup restore failed; check database and storage access\n")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    os.umask(0o077)
    asyncio.run(_main())
