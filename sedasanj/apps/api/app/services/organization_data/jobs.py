from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4
from zipfile import BadZipFile

from sqlalchemy import func, or_, select
from sqlalchemy.exc import DataError, IntegrityError

from app.config import get_settings
from app.db import control_session_scope, session_scope
from app.errors import ApiError
from app.models import (
    OrganizationBackupSettings,
    OrganizationDataRun,
    OrganizationImportReceipt,
    Tenant,
    User,
)
from app.services import audit
from app.services.audio_lifecycle import protect_tenant_media
from app.services.organization_data import archive, dataset, ftp
from app.services.platform_secrets import decrypt_secret, encrypt_secret
from app.services.storage import get_storage

logger = logging.getLogger(__name__)
RETRY_MINUTES = (5, 15, 60)
_ACTIVE = ("queued", "running")


def unavailable() -> ApiError:
    return ApiError(
        "org_archive_unavailable",
        "آماده‌سازی بک‌آپ انجام نشد. فضای ذخیره‌سازی و تنظیمات سامانه را بررسی کنید.",
        retryable=True,
    )


def store_secret(value: str) -> str:
    try:
        return encrypt_secret(value)
    except RuntimeError as exc:
        raise unavailable() from exc


def next_occurrence(
    after: datetime,
    timezone: str,
    cadence: str,
    local_time: str,
    weekday: int,
) -> datetime:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(timezone)
    start = after.astimezone(zone).date()
    clock = time.fromisoformat(local_time)
    for offset in range(15):
        day = start + timedelta(days=offset)
        if cadence == "weekly" and day.weekday() != weekday:
            continue
        local = datetime.combine(day, clock, zone)
        utc = local.astimezone(UTC)
        if utc > after and utc.astimezone(zone).replace(tzinfo=None) == local.replace(tzinfo=None):
            return utc
    raise ValueError("invalid backup schedule")


def new_run(
    tenant: UUID,
    actor: UUID | None,
    kind: str,
    secret: str,
    *,
    options: dict[str, Any] | None = None,
) -> OrganizationDataRun:
    now = datetime.now(UTC)
    return OrganizationDataRun(
        id=uuid4(),
        tenant_id=tenant,
        actor_id=actor,
        kind=kind,
        phase="preview" if kind == "import" else "export",
        state="uploading" if kind == "import" else "queued",
        secret=secret,
        options=options or {},
        due_at=now,
        created_at=now,
        expires_at=now + (timedelta(days=30) if kind == "scheduled" else timedelta(hours=24)),
    )


def run_prefix(run: OrganizationDataRun) -> str:
    return f"organization-archives/{run.tenant_id}/{run.id}"


def file_key(run: OrganizationDataRun) -> str:
    return f"{run_prefix(run)}/archive.sedasanj"


def imported_media_prefix(run: OrganizationDataRun) -> str:
    return f"{run.tenant_id}/restored/{run.id}"


def filename(run: OrganizationDataRun) -> str:
    stamp = run.created_at.astimezone(UTC).strftime("%Y%m%d-%H%M%SZ")
    suffix = ".gzip" if content_type(run) == "application/gzip" else ".sedasanj"
    return f"sedasanj-{stamp}-{run.id.hex}{suffix}"


def content_type(run: OrganizationDataRun) -> str:
    if (run.summary or {}).get("archive_format") == archive.GZIP_FORMAT:
        return "application/gzip"
    return "application/octet-stream"


def destination(options: dict[str, Any], secret: str) -> ftp.Destination:
    import base64

    password = base64.b64decode(decrypt_secret(secret)).decode()
    return ftp.Destination(
        protocol=options["protocol"],
        host=options["host"],
        port=options["port"],
        directory=options["directory"],
        username=options["username"],
        password=password,
    )


async def schedule_due() -> None:
    now = datetime.now(UTC)
    async with control_session_scope() as session:
        rows = (
            await session.execute(
                select(OrganizationBackupSettings, Tenant.timezone)
                .join(Tenant, Tenant.id == OrganizationBackupSettings.tenant_id)
                .where(
                    Tenant.status == "active",
                    OrganizationBackupSettings.enabled.is_(True),
                    OrganizationBackupSettings.next_run_at <= now,
                )
                .order_by(OrganizationBackupSettings.next_run_at)
                .with_for_update(of=OrganizationBackupSettings, skip_locked=True)
                .limit(20)
            )
        ).all()
        for settings, timezone in rows:
            if settings.recovery_secret and settings.ftp_secret:
                session.add(
                    new_run(
                        settings.tenant_id,
                        None,
                        "scheduled",
                        settings.recovery_secret,
                        options={
                            "destination": settings.destination,
                            "ftp_secret": settings.ftp_secret,
                        },
                    )
                )
            settings.next_run_at = next_occurrence(
                now,
                timezone,
                settings.cadence,
                settings.local_time,
                settings.weekday,
            )


async def _download(run: OrganizationDataRun, target: Path) -> None:
    limit = get_settings().org_archive_max_bytes
    size = 0
    digest = hashlib.sha256()
    with target.open("wb") as output:
        async for block in get_storage().iter_chunks(file_key(run)):
            size += len(block)
            if size > limit:
                raise archive.archive_too_large()
            output.write(block)
            digest.update(block)
    if run.size_bytes != size or (run.checksum and run.checksum != digest.hexdigest()):
        raise archive.invalid_archive()


async def _export(run: OrganizationDataRun, workspace: Path) -> None:
    settings = get_settings()
    source, target = workspace / "data.zip", workspace / "archive.sedasanj"
    gzip_payload = settings.org_archive_write_v2 or run.tenant_id in settings.org_archive_v2_tenants
    async with protect_tenant_media(run.tenant_id):
        summary = await dataset.export_zip(
            run.tenant_id,
            source,
            settings.org_archive_expanded_max_bytes,
            gzip_payload=gzip_payload,
        )
    if gzip_payload:
        summary["archive_format"] = archive.GZIP_FORMAT
    key = archive.recovery_key(decrypt_secret(run.secret or ""))
    size, checksum = await asyncio.to_thread(
        archive.seal_gzip if gzip_payload else archive.seal,
        source,
        target,
        key,
        settings.org_archive_max_bytes,
    )
    storage = get_storage()
    await storage.ensure_bucket()
    media_type = "application/gzip" if gzip_payload else "application/octet-stream"
    await storage.put_path(file_key(run), target, content_type=media_type)
    if gzip_payload:
        remote_size = 0
        remote_hash = hashlib.sha256()
        async for block in storage.iter_chunks(file_key(run)):
            remote_size += len(block)
            if remote_size > size:
                break
            remote_hash.update(block)
        if remote_size != size or remote_hash.hexdigest() != checksum:
            await storage.delete(file_key(run))
            raise unavailable()
    async with control_session_scope() as session:
        row = await session.get(OrganizationDataRun, run.id, with_for_update=True)
        if row is not None:
            row.state, row.summary, row.size_bytes, row.checksum = (
                "succeeded",
                summary,
                size,
                checksum,
            )
            row.secret, row.error_code, row.completed_at = None, None, datetime.now(UTC)
            if row.kind == "scheduled":
                row.phase, row.transfer_state = "transfer", "queued"
            else:
                row.options = {}


async def _restore(run: OrganizationDataRun, workspace: Path) -> None:
    actor = run.actor_id
    if actor is None:
        raise unavailable()
    applying = run.phase == "apply"
    async with control_session_scope() as control:
        role = await control.scalar(
            select(User.role).where(
                User.id == actor,
                User.tenant_id == run.tenant_id,
            )
        )
        if role != "org_admin":
            raise ApiError("forbidden", "دسترسی مدیر تغییر کرده است. دوباره وارد شوید.")
    result = None
    if applying:
        async with session_scope(run.tenant_id) as session:
            receipt = await session.get(OrganizationImportReceipt, run.id)
            if receipt is not None:
                result = receipt.summary
    if result is None:
        source, target = workspace / "archive.sedasanj", workspace / "data.zip"
        await _download(run, source)
        settings = get_settings()
        key = archive.recovery_key(decrypt_secret(run.secret or ""))
        gzip_payload = archive.is_gzip(source)
        if gzip_payload:
            await asyncio.to_thread(
                archive.unseal_gzip,
                source,
                target,
                key,
                settings.org_archive_max_bytes,
                settings.org_archive_expanded_max_bytes,
            )
        else:
            await asyncio.to_thread(
                archive.unseal, source, target, key, settings.org_archive_max_bytes
            )
        source.unlink()
        mappings = {uid: UUID(target) for uid, target in run.options.get("mappings", {}).items()}
        with archive.open_zip(target) as data:
            async with session_scope(run.tenant_id) as session:
                transaction = await session.begin_nested()
                result = await dataset.restore_zip(
                    session,
                    data,
                    tenant=run.tenant_id,
                    actor=actor,
                    mappings=mappings,
                    workspace=workspace,
                    media_prefix=imported_media_prefix(run),
                    expanded_limit=settings.org_archive_expanded_max_bytes,
                    preview=not applying,
                    expected=run.summary if applying else None,
                    expected_version=2 if gzip_payload else 1,
                )
                if applying:
                    session.add(
                        OrganizationImportReceipt(
                            run_id=run.id,
                            tenant_id=run.tenant_id,
                            summary=result,
                        )
                    )
                    await audit.record(
                        session,
                        actor_type="user",
                        actor_id=actor,
                        tenant_id=run.tenant_id,
                        action="organization.archive.imported",
                        payload={"run_id": str(run.id), "counts": result["counts"]},
                    )
                    await transaction.commit()
                else:
                    await transaction.rollback()
    async with control_session_scope() as session:
        row = await session.get(OrganizationDataRun, run.id, with_for_update=True)
        if row is not None:
            row.summary = result
            row.state = "succeeded" if applying else "review"
            row.error_code = None
            if applying:
                row.completed_at, row.secret, row.options = datetime.now(UTC), None, {}


async def _transfer(run: OrganizationDataRun, workspace: Path) -> None:
    path = workspace / "archive.sedasanj"
    await _download(run, path)
    await asyncio.to_thread(
        ftp.transfer,
        destination(run.options["destination"], run.options["ftp_secret"]),
        path,
        filename(run),
        allow_plain=get_settings().org_backup_allow_plain_ftp,
        timeout=3600,
    )
    async with control_session_scope() as session:
        row = await session.get(OrganizationDataRun, run.id, with_for_update=True)
        if row is not None:
            row.transfer_state, row.options, row.error_code = "succeeded", {}, None


async def _record_failure(run: OrganizationDataRun, error: ApiError) -> None:
    async with control_session_scope() as session:
        row = await session.get(OrganizationDataRun, run.id, with_for_update=True)
        if row is None:
            return
        row.error_code = error.code
        if row.phase == "transfer":
            row.transfer_attempts += 1
            attempt = row.transfer_attempts
            if error.retryable and attempt <= len(RETRY_MINUTES):
                row.transfer_state = "queued"
                row.due_at = datetime.now(UTC) + timedelta(minutes=RETRY_MINUTES[attempt - 1])
            else:
                row.transfer_state, row.options = "failed", {}
        elif row.kind == "import" and error.code == "org_archive_review_changed":
            row.state, row.phase = "queued", "preview"
        elif row.kind == "import" and error.code == "org_archive_mapping":
            row.state, row.phase = "review", "preview"
        else:
            row.state, row.secret, row.options = "failed", None, {}
            row.completed_at = datetime.now(UTC)


async def _cleanup(run: OrganizationDataRun) -> None:
    storage = get_storage()
    if run.kind == "import" and run.phase == "apply" and run.state != "succeeded":
        async with session_scope(run.tenant_id) as session:
            receipt = await session.get(OrganizationImportReceipt, run.id)
        if receipt is None:
            for key, _ in await storage.list_keys(f"{imported_media_prefix(run)}/"):
                await storage.delete(key)
    if await storage.exists(file_key(run)):
        await storage.delete(file_key(run))


async def _locked(session: Any, tenant: UUID) -> bool:
    return bool(
        await session.scalar(
            select(
                func.pg_try_advisory_xact_lock(
                    func.hashtextextended(f"organization-data:{tenant}", 0)
                )
            )
        )
    )


async def expire_one() -> None:
    now = datetime.now(UTC)
    async with control_session_scope() as session:
        candidates = (
            await session.scalars(
                select(OrganizationDataRun)
                .where(
                    OrganizationDataRun.expires_at <= now, OrganizationDataRun.state != "expired"
                )
                .order_by(OrganizationDataRun.expires_at)
                .limit(20)
            )
        ).all()
        for run in candidates:
            if not await _locked(session, run.tenant_id):
                continue
            if run.state == "uploading":
                await session.refresh(run, with_for_update=True)
            await _cleanup(run)
            run.state, run.secret, run.options = "expired", None, {}
            if run.kind == "import":
                run.summary = {}
            if run.transfer_state in _ACTIVE:
                run.transfer_state = "failed"
            break


async def run_one() -> bool:
    now = datetime.now(UTC)
    async with control_session_scope() as lock_session:
        candidates = (
            await lock_session.scalars(
                select(OrganizationDataRun)
                .join(Tenant, Tenant.id == OrganizationDataRun.tenant_id)
                .where(
                    Tenant.status == "active",
                    OrganizationDataRun.due_at <= now,
                    OrganizationDataRun.expires_at > now,
                    or_(
                        OrganizationDataRun.state.in_(_ACTIVE),
                        OrganizationDataRun.transfer_state.in_(_ACTIVE),
                    ),
                )
                .order_by(OrganizationDataRun.due_at, OrganizationDataRun.id)
                .limit(25)
            )
        ).all()
        for candidate in candidates:
            if not await _locked(lock_session, candidate.tenant_id):
                continue
            async with control_session_scope() as session:
                run = await session.get(OrganizationDataRun, candidate.id, with_for_update=True)
                if run is None or run.due_at > now or run.expires_at <= now:
                    continue
                if run.phase != "transfer":
                    tenant_status = await lock_session.scalar(
                        select(Tenant.status)
                        .where(Tenant.id == run.tenant_id)
                        .with_for_update(read=True)
                    )
                    if tenant_status != "active":
                        continue
                if run.phase == "transfer" and run.transfer_state in _ACTIVE:
                    run.transfer_state = "running"
                elif run.state in _ACTIVE:
                    run.state = "running"
                else:
                    continue
            try:
                with TemporaryDirectory(prefix="sedasanj-organization-") as directory:
                    workspace = Path(directory)
                    if run.phase == "export":
                        await _export(run, workspace)
                    elif run.phase == "transfer":
                        await _transfer(run, workspace)
                    else:
                        await _restore(run, workspace)
            except ApiError as exc:
                await _record_failure(run, exc)
            except (BadZipFile, DataError, IntegrityError, ValueError, TypeError, KeyError):
                await _record_failure(run, archive.invalid_archive())
            except Exception as exc:
                logger.error("organization data run failed: %s (%s)", run.id, type(exc).__name__)
                await _record_failure(run, unavailable())
            if run.kind == "import" and run.phase == "apply":
                async with control_session_scope() as session:
                    state = await session.scalar(
                        select(OrganizationDataRun.state).where(
                            OrganizationDataRun.id == run.id,
                        )
                    )
                if state in {"failed", "succeeded"}:
                    await _cleanup(run)
            return True
    return False
