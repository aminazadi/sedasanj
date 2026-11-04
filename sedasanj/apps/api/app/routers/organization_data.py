from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any, Literal
from uuid import UUID

import jwt
from fastapi import APIRouter, Cookie, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.config import get_settings
from app.db import control_session_scope
from app.deps import OrgAdminDep, Principal, client_ip
from app.errors import ApiError
from app.models import OrganizationBackupSettings, OrganizationDataRun, Tenant, User
from app.services import audit, ratelimit
from app.services.organization_data import archive, ftp, jobs
from app.services.storage import get_storage

router = APIRouter(prefix="/v1/account/data", tags=["account"])
COOKIE = "sedasanj_archive_download"
AUDIENCE = "sedasanj-organization-archive"


class DestinationInput(BaseModel):
    protocol: Literal["ftps", "ftp"] = "ftps"
    host: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9.:-]+$")
    port: int = Field(default=21, ge=1, le=65535)
    directory: str = Field(default="/", min_length=1, max_length=1024)
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr | None = Field(default=None, max_length=1024)


class BackupInput(BaseModel):
    enabled: bool = False
    cadence: Literal["daily", "weekly"] = "daily"
    local_time: str = Field(default="02:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    weekday: int = Field(default=5, ge=0, le=6)
    destination: DestinationInput | None = None


class RecoveryInput(BaseModel):
    key: SecretStr = Field(min_length=43, max_length=43)


class ReviewInput(BaseModel):
    mappings: dict[UUID, UUID] = Field(default_factory=dict, max_length=10_000)


def _tenant(principal: Principal) -> UUID:
    assert principal.tenant_id is not None
    return principal.tenant_id


def _now() -> datetime:
    return datetime.now(UTC)


def _missing() -> ApiError:
    return ApiError("not_found", "عملیات پیدا نشد. تاریخچه را تازه کنید.")


def _wrong_state() -> ApiError:
    return ApiError(
        "conflict", "وضعیت عملیات تغییر کرده است. صفحه را تازه کنید و دوباره تلاش کنید."
    )


async def _audit(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    action: str,
    run_id: UUID | None = None,
) -> None:
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=_tenant(principal),
        action=f"organization.archive.{action}",
        payload={"run_id": str(run_id)} if run_id else {},
        ip=client_ip(request),
    )


async def _settings(
    session: AsyncSession,
    tenant: UUID,
    *,
    lock: bool = False,
) -> OrganizationBackupSettings:
    if lock:
        await session.execute(
            insert(OrganizationBackupSettings)
            .values(
                tenant_id=tenant,
                enabled=False,
                cadence="daily",
                local_time="02:00",
                weekday=5,
                destination={},
            )
            .on_conflict_do_nothing()
        )
    row = await session.get(OrganizationBackupSettings, tenant, with_for_update=lock)
    return row or OrganizationBackupSettings(
        tenant_id=tenant,
        enabled=False,
        cadence="daily",
        local_time="02:00",
        weekday=5,
        destination={},
    )


async def _settings_view(
    session: AsyncSession,
    tenant: UUID,
    row: OrganizationBackupSettings,
) -> dict[str, Any]:
    timezone = await session.scalar(select(Tenant.timezone).where(Tenant.id == tenant))
    config = get_settings()
    return {
        "enabled": row.enabled,
        "cadence": row.cadence,
        "local_time": row.local_time,
        "weekday": row.weekday,
        "destination": row.destination,
        "timezone": timezone,
        "next_run_at": row.next_run_at,
        "has_password": bool(row.ftp_secret),
        "has_recovery_key": bool(row.recovery_secret),
        "allow_plain_ftp": config.org_backup_allow_plain_ftp,
        "max_bytes": config.org_archive_max_bytes,
    }


def _ftp_options(
    target: DestinationInput,
    stored: OrganizationBackupSettings,
) -> tuple[dict[str, Any], str]:
    options = target.model_dump(exclude={"password"})
    options["host"] = target.host.lower().rstrip(".")
    if target.protocol == "ftp" and not get_settings().org_backup_allow_plain_ftp:
        raise ftp.destination_error()
    if (
        not options["host"]
        or any(
            ord(char) < 32 or ord(char) == 127
            for value in (target.directory, target.username)
            for char in value
        )
        or any(part == ".." for part in target.directory.split("/"))
    ):
        raise ftp.destination_error()
    password = target.password.get_secret_value() if target.password else ""
    if password:
        if any(ord(char) < 32 or ord(char) == 127 for char in password):
            raise ftp.destination_error()
        secret = jobs.store_secret(base64.b64encode(password.encode()).decode())
    else:
        stored_secret = stored.ftp_secret
        if not stored_secret or any(
            options[key] != stored.destination.get(key)
            for key in ("protocol", "host", "port", "username")
        ):
            raise ApiError("org_backup_destination", "گذرواژهٔ مقصد را وارد و اتصال را تست کنید.")
        secret = stored_secret
    return options, secret


@router.get("/backup/settings")
async def get_backup_settings(principal: OrgAdminDep) -> dict[str, Any]:
    tenant = _tenant(principal)
    async with control_session_scope() as session:
        return await _settings_view(session, tenant, await _settings(session, tenant))


@router.put("/backup/settings")
async def update_backup_settings(
    request: Request,
    payload: BackupInput,
    principal: OrgAdminDep,
) -> dict[str, Any]:
    tenant = _tenant(principal)
    async with control_session_scope() as session:
        row = await _settings(session, tenant, lock=True)
        if payload.destination is not None:
            options, secret = _ftp_options(payload.destination, row)
            await asyncio.to_thread(ftp.public_address, options["host"], options["port"])
            row.destination, row.ftp_secret = options, secret
        if payload.destination is None and "destination" in payload.model_fields_set:
            row.destination, row.ftp_secret = {}, None
        if payload.enabled and (
            not row.recovery_secret or not row.destination or not row.ftp_secret
        ):
            raise ApiError(
                "org_backup_destination",
                "ابتدا کلید بازیابی و مقصد بک‌آپ را تنظیم کنید.",
            )
        if (
            payload.enabled
            and row.destination.get("protocol") == "ftp"
            and (not get_settings().org_backup_allow_plain_ftp)
        ):
            raise ftp.destination_error()
        row.enabled, row.cadence = payload.enabled, payload.cadence
        row.local_time, row.weekday = payload.local_time, payload.weekday
        if payload.enabled:
            zone = await session.scalar(select(Tenant.timezone).where(Tenant.id == tenant))
            row.next_run_at = jobs.next_occurrence(
                _now(),
                zone or "UTC",
                row.cadence,
                row.local_time,
                row.weekday,
            )
        else:
            row.next_run_at = None
        await _audit(session, request, principal, "settings_updated")
        return await _settings_view(session, tenant, row)


@router.put("/backup/recovery-key")
async def save_recovery_key(
    request: Request,
    payload: RecoveryInput,
    principal: OrgAdminDep,
) -> dict[str, Any]:
    tenant = _tenant(principal)
    value = payload.key.get_secret_value()
    archive.recovery_key(value)
    encrypted = jobs.store_secret(value)
    async with control_session_scope() as session:
        row = await _settings(session, tenant, lock=True)
        row.recovery_secret = encrypted
        await _audit(session, request, principal, "recovery_key_updated")
        return await _settings_view(session, tenant, row)


@router.post("/backup/test", status_code=204)
async def test_backup_destination(
    request: Request,
    payload: DestinationInput,
    principal: OrgAdminDep,
) -> None:
    tenant = _tenant(principal)
    await ratelimit.enforce(f"organization-backup-test:{tenant}", 5)
    async with control_session_scope() as session:
        options, secret = _ftp_options(payload, await _settings(session, tenant))
    target = jobs.destination(options, secret)
    with TemporaryDirectory(prefix="sedasanj-ftp-test-") as directory:
        path = Path(directory) / "probe"
        path.write_bytes(b"SedaSanj FTP connection test\n")
        await asyncio.to_thread(
            ftp.test_destination,
            target,
            path,
            allow_plain=get_settings().org_backup_allow_plain_ftp,
        )
    async with control_session_scope() as session:
        await _audit(session, request, principal, "destination_tested")


def _view(run: OrganizationDataRun, principal: Principal) -> dict[str, Any]:
    summary = run.summary
    if run.kind == "import" and run.actor_id != principal.id:
        summary = {key: value for key, value in summary.items() if key != "owners"}
    return {
        "id": run.id,
        "kind": run.kind,
        "phase": run.phase,
        "state": run.state,
        "transfer_state": run.transfer_state,
        "transfer_attempts": run.transfer_attempts,
        "next_attempt_at": run.due_at if run.transfer_state == "queued" else None,
        "error_code": run.error_code,
        "size_bytes": run.size_bytes,
        "summary": summary,
        "checksum": run.checksum,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "expires_at": run.expires_at,
        "can_upload": run.kind == "import"
        and run.actor_id == principal.id
        and run.state == "uploading",
        "can_review": run.kind == "import"
        and run.actor_id == principal.id
        and run.state == "review",
        "can_download": run.kind != "import"
        and run.state == "succeeded"
        and run.expires_at > _now(),
    }


async def _run(
    session: AsyncSession,
    run_id: UUID,
    principal: Principal,
    *,
    lock: bool = False,
) -> OrganizationDataRun:
    query = select(OrganizationDataRun).where(
        OrganizationDataRun.id == run_id,
        OrganizationDataRun.tenant_id == _tenant(principal),
    )
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise _missing()
    return row


@router.get("/runs")
async def list_runs(
    principal: OrgAdminDep,
    kind: Literal["manual", "scheduled", "import"] | None = None,
    state: Literal["active", "review", "succeeded", "failed", "expired"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 15,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> dict[str, Any]:
    rows = select(OrganizationDataRun).where(OrganizationDataRun.tenant_id == _tenant(principal))
    if kind:
        rows = rows.where(OrganizationDataRun.kind == kind)
    if state == "active":
        rows = rows.where(
            or_(
                OrganizationDataRun.state.in_(("uploading", "queued", "running")),
                OrganizationDataRun.transfer_state.in_(("queued", "running")),
            )
        )
    elif state:
        rows = rows.where(
            or_(OrganizationDataRun.state == state, OrganizationDataRun.transfer_state == state)
            if state == "failed"
            else OrganizationDataRun.state == state
        )
    async with control_session_scope() as session:
        total = await session.scalar(select(func.count()).select_from(rows.subquery()))
        page = (
            await session.scalars(
                rows.order_by(
                    OrganizationDataRun.created_at.desc(),
                    OrganizationDataRun.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return {"total": total, "items": [_view(row, principal) for row in page]}


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, principal: OrgAdminDep) -> dict[str, Any]:
    async with control_session_scope() as session:
        return _view(await _run(session, run_id, principal), principal)


@router.post("/backup", status_code=202)
async def start_backup(request: Request, principal: OrgAdminDep) -> dict[str, Any]:
    tenant = _tenant(principal)
    await ratelimit.enforce(f"organization-backup-start:{tenant}", 5)
    async with control_session_scope() as session:
        settings = await _settings(session, tenant, lock=True)
        if not settings.recovery_secret:
            raise ApiError("org_archive_invalid", "ابتدا کلید بازیابی را بسازید و نگه دارید.")
        active = await session.scalar(
            select(OrganizationDataRun.id)
            .where(
                OrganizationDataRun.tenant_id == tenant,
                OrganizationDataRun.kind == "manual",
                OrganizationDataRun.state.in_(("queued", "running")),
                OrganizationDataRun.expires_at > _now(),
            )
            .limit(1)
        )
        if active:
            raise _wrong_state()
        row = jobs.new_run(tenant, principal.id, "manual", settings.recovery_secret)
        session.add(row)
        await _audit(session, request, principal, "backup_queued", row.id)
        return _view(row, principal)


@router.get("/import/members")
async def get_members(principal: OrgAdminDep) -> list[dict[str, Any]]:
    async with control_session_scope() as session:
        members = (
            await session.execute(
                select(User.id, User.email, User.role)
                .where(User.tenant_id == _tenant(principal))
                .order_by(User.email)
                .limit(10000)
            )
        ).all()
        return [{"id": row.id, "label": row.email, "role": row.role} for row in members]


@router.post("/import", status_code=201)
async def start_import(
    request: Request,
    payload: RecoveryInput,
    principal: OrgAdminDep,
) -> dict[str, Any]:
    tenant = _tenant(principal)
    await ratelimit.enforce(f"organization-import-start:{tenant}", 5)
    key = payload.key.get_secret_value()
    archive.recovery_key(key)
    async with control_session_scope() as session:
        await _settings(session, tenant, lock=True)
        active = await session.scalar(
            select(OrganizationDataRun.id)
            .where(
                OrganizationDataRun.tenant_id == tenant,
                OrganizationDataRun.kind == "import",
                OrganizationDataRun.state.in_(("uploading", "queued", "running", "review")),
                OrganizationDataRun.expires_at > _now(),
            )
            .limit(1)
        )
        if active:
            raise ApiError("conflict", "یک ورود فعال است. آن را در تاریخچه ادامه دهید یا لغو کنید.")
        row = jobs.new_run(tenant, principal.id, "import", jobs.store_secret(key))
        session.add(row)
        await _audit(session, request, principal, "import_started", row.id)
        return _view(row, principal)


def _assert_import(row: OrganizationDataRun, principal: Principal, state: str) -> None:
    if row.kind != "import" or row.actor_id != principal.id:
        raise _missing()
    if row.state != state or row.expires_at <= _now():
        raise _wrong_state()


@router.put("/import/{run_id}/file", status_code=202)
async def upload_import(run_id: UUID, request: Request, principal: OrgAdminDep) -> dict[str, Any]:
    if request.headers.get("content-type") != "application/octet-stream":
        raise archive.invalid_archive()
    limit = get_settings().org_archive_max_bytes
    header = request.headers.get("content-length")
    if header and (
        not header.isascii() or not header.isdecimal() or len(header) > 12 or int(header) > limit
    ):
        raise archive.archive_too_large()
    async with control_session_scope() as session:
        row = await _run(session, run_id, principal, lock=True)
        _assert_import(row, principal, "uploading")
        with TemporaryDirectory(prefix="sedasanj-archive-upload-") as directory:
            path = Path(directory) / "archive.sedasanj"
            size = 0
            try:
                with path.open("wb") as output:
                    async for block in request.stream():
                        size += len(block)
                        if size > limit:
                            raise archive.archive_too_large()
                        output.write(block)
            except ClientDisconnect as exc:
                raise archive.invalid_archive() from exc
            except OSError as exc:
                raise jobs.unavailable() from exc
            with path.open("rb") as source:
                if source.read(len(archive.MAGIC)) != archive.MAGIC:
                    raise archive.invalid_archive()
            storage = get_storage()
            try:
                await storage.ensure_bucket()
                await storage.put_path(
                    jobs.file_key(row), path, content_type="application/octet-stream"
                )
            except Exception as exc:
                raise jobs.unavailable() from exc
        row.size_bytes, row.state, row.due_at = size, "queued", _now()
        await _audit(session, request, principal, "file_uploaded", row.id)
        return _view(row, principal)


@router.put("/import/{run_id}/mapping", status_code=202)
async def update_mapping(
    run_id: UUID,
    request: Request,
    payload: ReviewInput,
    principal: OrgAdminDep,
) -> dict[str, Any]:
    async with control_session_scope() as session:
        row = await _run(session, run_id, principal, lock=True)
        _assert_import(row, principal, "review")
        known = {item["id"] for item in row.summary.get("owners", [])}
        targets = set(payload.mappings.values())
        matches = set(
            (
                await session.scalars(
                    select(User.id).where(
                        User.tenant_id == _tenant(principal),
                        User.id.in_(targets),
                    )
                )
            ).all()
        )
        if targets != matches or any(str(uid) not in known for uid in payload.mappings):
            raise ApiError("org_archive_mapping", "نگاشت اعضای مقصد را دوباره انتخاب کنید.")
        row.options = {
            "mappings": {str(uid): str(target) for uid, target in payload.mappings.items()}
        }
        row.phase, row.state, row.due_at = "preview", "queued", _now()
        await _audit(session, request, principal, "mapping_updated", row.id)
        return _view(row, principal)


@router.post("/import/{run_id}/confirm", status_code=202)
async def confirm_import(run_id: UUID, request: Request, principal: OrgAdminDep) -> dict[str, Any]:
    async with control_session_scope() as session:
        row = await _run(session, run_id, principal, lock=True)
        _assert_import(row, principal, "review")
        if not row.summary or row.error_code == "org_archive_mapping":
            raise _wrong_state()
        row.phase, row.state, row.due_at = "apply", "queued", _now()
        await _audit(session, request, principal, "import_confirmed", row.id)
        return _view(row, principal)


@router.delete("/import/{run_id}", status_code=204)
async def cancel_import(run_id: UUID, request: Request, principal: OrgAdminDep) -> None:
    async with control_session_scope() as session:
        row = await _run(session, run_id, principal, lock=True)
        if row.kind != "import" or row.actor_id != principal.id:
            raise _missing()
        if row.state not in {"uploading", "review"}:
            raise _wrong_state()
        row.expires_at, row.secret, row.options = _now(), None, {}
        await _audit(session, request, principal, "import_cancelled", row.id)


@router.post("/runs/{run_id}/download", status_code=204)
async def authorize_download(
    run_id: UUID,
    request: Request,
    response: Response,
    principal: OrgAdminDep,
) -> None:
    async with control_session_scope() as session:
        row = await _run(session, run_id, principal)
        if not _view(row, principal)["can_download"]:
            raise _missing()
        await _audit(session, request, principal, "download_authorized", row.id)
    settings = get_settings()
    ticket = jwt.encode(
        {
            "sub": str(principal.id),
            "tenant": str(_tenant(principal)),
            "run": str(run_id),
            "aud": AUDIENCE,
            "exp": _now() + timedelta(seconds=120),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE,
        ticket,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        path=f"/v1/account/data/runs/{run_id}/download",
        max_age=120,
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/runs/{run_id}/download", include_in_schema=False)
async def download_backup(
    run_id: UUID,
    ticket: Annotated[str | None, Cookie(alias=COOKIE)] = None,
) -> StreamingResponse:
    try:
        claims = jwt.decode(
            ticket or "",
            get_settings().jwt_secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "tenant", "run"]},
        )
        actor, tenant = UUID(claims["sub"]), UUID(claims["tenant"])
        if claims["run"] != str(run_id):
            raise ValueError("download ticket scope mismatch")
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise _missing() from exc
    async with control_session_scope() as session:
        row = await session.get(OrganizationDataRun, run_id)
        authorized = await session.scalar(
            select(User.id)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.id == actor,
                User.tenant_id == tenant,
                User.role == "org_admin",
                Tenant.status == "active",
            )
        )
        if (
            not authorized
            or not row
            or row.tenant_id != tenant
            or row.kind == "import"
            or row.state != "succeeded"
            or row.expires_at <= _now()
        ):
            raise _missing()
    return StreamingResponse(
        get_storage().iter_chunks(jobs.file_key(row)),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{jobs.filename(row)}"',
            "Content-Length": str(row.size_bytes),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
