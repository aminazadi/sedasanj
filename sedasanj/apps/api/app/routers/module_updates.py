"""FreePBX module releases: staff publishing, on-host update checks, and the tenant changelog."""

from __future__ import annotations

import re
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import control_session_scope
from app.deps import (
    ApiKeyDep,
    OrgAdminDep,
    Principal,
    StaffDep,
    StaffSession,
    UserDep,
    client_ip,
    require_staff_roles,
)
from app.errors import ApiError
from app.models import (
    ModuleDiagnostic,
    ModuleInstallation,
    ModuleRelease,
    ModuleUpdateEvent,
    Tenant,
)
from app.schemas import (
    ModuleChangelogEntry,
    ModuleChannel,
    ModuleDiagnosticIn,
    ModuleDiagnosticOut,
    ModuleInstallationOut,
    ModuleReleaseOut,
    ModuleReleaseUpdate,
    ModuleSeverity,
    ModuleUpdateCheckOut,
    ModuleUpdateOffer,
    ModuleUpdateReportIn,
    ModuleZipInspection,
    StaffSensitiveAction,
)
from app.services import audit, ratelimit
from app.services import module_releases as releases
from app.services.processing_events import sanitize_detail
from app.services.storage import get_storage

router = APIRouter(tags=["module-updates"])

ReleaseAdminDep = Annotated[Principal, Depends(require_staff_roles("super_admin"))]


# --- helpers ----------------------------------------------------------------


async def _spool_upload(upload: UploadFile) -> Path:
    """Stream the multipart body to disk so a 60 MB zip never sits in memory."""
    limit = get_settings().max_module_release_bytes
    written = 0
    with tempfile.NamedTemporaryFile(
        prefix="module-release-", suffix=".zip", delete=False
    ) as handle:
        path = Path(handle.name)
        try:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise ApiError("archive_too_large", "module zip is larger than allowed")
                handle.write(chunk)
        except BaseException:
            handle.close()
            path.unlink(missing_ok=True)
            raise
    return path


async def _published(session: AsyncSession, product: str) -> list[ModuleRelease]:
    rows = await session.execute(
        select(ModuleRelease).where(
            ModuleRelease.product == product, ModuleRelease.status == "published"
        )
    )
    return list(rows.scalars().all())


def _newest(rows: list[ModuleRelease]) -> ModuleRelease | None:
    return max(
        rows,
        key=lambda row: (row.version_major, row.version_minor, row.version_patch),
        default=None,
    )


def _key(version: str) -> tuple[int, int, int]:
    return releases.parse_version(version)


def _entry(release: ModuleRelease) -> ModuleChangelogEntry:
    return ModuleChangelogEntry(
        id=release.id,
        version=release.version,
        title=release.title,
        severity=release.severity,  # type: ignore[arg-type]
        html=release.changelog_html,
        published_at=release.published_at,
    )


async def _release_out(session: AsyncSession, release: ModuleRelease) -> ModuleReleaseOut:
    count = (
        await session.execute(
            select(func.count(ModuleInstallation.id)).where(
                ModuleInstallation.product == release.product,
                ModuleInstallation.module_version == release.version,
            )
        )
    ).scalar_one()
    out = ModuleReleaseOut.model_validate(release)
    out.installations = int(count)
    return out


def _check_metadata(min_from_version: str | None) -> str | None:
    value = (min_from_version or "").strip() or None
    if value is not None:
        releases.parse_version(value)
    return value


def _stream(key: str) -> AsyncIterator[bytes]:
    return get_storage().iter_chunks(key)


def _download_response(release: ModuleRelease) -> StreamingResponse:
    return StreamingResponse(
        _stream(release.artifact_key),
        media_type="application/zip",
        headers={
            "Content-Length": str(release.artifact_size),
            "Content-Disposition": f'attachment; filename="asterisk-module-{release.version}.zip"',
            "X-Checksum-Sha256": release.artifact_sha256,
            "X-Signature-Ed25519": release.signature_b64,
        },
    )


# --- staff: /v1/admin/module-releases ---------------------------------------


@router.get("/v1/admin/module-releases")
async def admin_list_module_releases(
    staff: StaffDep,
    session: StaffSession,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    product: str = releases.PRODUCT_FREEPBX,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    query = select(ModuleRelease).where(ModuleRelease.product == product)
    if status_filter:
        query = query.where(ModuleRelease.status == status_filter)
    total = int(
        (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    )
    rows = (
        (
            await session.execute(
                query.order_by(
                    ModuleRelease.version_major.desc(),
                    ModuleRelease.version_minor.desc(),
                    ModuleRelease.version_patch.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    counts = dict(
        (
            await session.execute(
                select(ModuleInstallation.module_version, func.count(ModuleInstallation.id))
                .where(ModuleInstallation.product == product)
                .group_by(ModuleInstallation.module_version)
            )
        )
        .tuples()
        .all()
    )
    items = []
    for row in rows:
        out = ModuleReleaseOut.model_validate(row)
        out.installations = int(counts.get(row.version, 0))
        items.append(out)
    return {
        "items": items,
        "total": total,
        "next_cursor": str(offset + limit) if offset + len(rows) < total else None,
    }


@router.get("/v1/admin/module-releases/signing-key")
async def admin_module_signing_key(staff: StaffDep) -> dict[str, str]:
    """The public half that ships in the module as assets/release-signing.pub."""
    return {"algorithm": "ed25519", "public_key_b64": releases.public_key_b64()}


@router.post("/v1/admin/module-releases/inspect", response_model=ModuleZipInspection)
async def admin_inspect_module_zip(
    staff: ReleaseAdminDep,
    session: StaffSession,
    file: Annotated[UploadFile, File()],
) -> ModuleZipInspection:
    path = await _spool_upload(file)
    try:
        inspection = releases.inspect_zip(path)
    finally:
        path.unlink(missing_ok=True)
    newest = _newest(await _published(session, releases.PRODUCT_FREEPBX))
    exists = (
        await session.execute(
            select(ModuleRelease.id).where(
                ModuleRelease.product == releases.PRODUCT_FREEPBX,
                ModuleRelease.version == inspection.version,
            )
        )
    ).scalar_one_or_none()
    return ModuleZipInspection(
        rawname=inspection.rawname,
        version=inspection.version,
        sha256=inspection.sha256,
        size=inspection.size,
        latest_published=newest.version if newest else None,
        already_exists=exists is not None,
    )


@router.post(
    "/v1/admin/module-releases",
    response_model=ModuleReleaseOut,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_module_release(
    request: Request,
    staff: ReleaseAdminDep,
    session: StaffSession,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=200)] = None,
    changelog_html: Annotated[str, Form(max_length=200_000)] = "",
    severity: Annotated[ModuleSeverity, Form()] = "normal",
    channel: Annotated[ModuleChannel, Form()] = "stable",
    min_freepbx_major: Annotated[int | None, Form(ge=13, le=99)] = None,
    max_freepbx_major: Annotated[int | None, Form(ge=13, le=99)] = None,
    min_php_version: Annotated[str | None, Form(pattern=r"^\d{1,2}\.\d{1,2}(\.\d{1,3})?$")] = None,
    min_from_version: Annotated[str | None, Form(max_length=32)] = None,
) -> ModuleReleaseOut:
    path = await _spool_upload(file)
    try:
        inspection = releases.inspect_zip(path)
        product = releases.PRODUCT_FREEPBX
        duplicate = (
            await session.execute(
                select(ModuleRelease.id).where(
                    ModuleRelease.product == product, ModuleRelease.version == inspection.version
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ApiError("invalid_request", f"version {inspection.version} already exists")
        newest = _newest(await _published(session, product))
        if newest is not None and _key(inspection.version) <= _key(newest.version):
            raise ApiError(
                "invalid_request",
                f"version {inspection.version} must be newer than published {newest.version}",
            )
        releases.embed_signing_public_key(path)
        inspection = releases.inspect_zip(path)
        safe_html, plain = releases.sanitize_changelog(changelog_html)
        signature = releases.sign_digest(inspection.sha256)
        key = releases.artifact_key(product, inspection.version)
        await get_storage().put_path(key, path, content_type="application/zip")
    finally:
        path.unlink(missing_ok=True)
    major, minor, patch = releases.parse_version(inspection.version)
    release = ModuleRelease(
        product=product,
        version=inspection.version,
        version_major=major,
        version_minor=minor,
        version_patch=patch,
        title=(title or "").strip() or f"نسخهٔ {inspection.version}",
        changelog_html=safe_html,
        changelog_plain=plain,
        severity=severity,
        channel=channel,
        min_freepbx_major=min_freepbx_major,
        max_freepbx_major=max_freepbx_major,
        min_php_version=min_php_version,
        min_from_version=_check_metadata(min_from_version),
        artifact_key=key,
        artifact_sha256=inspection.sha256,
        artifact_size=inspection.size,
        signature_b64=signature,
        status="draft",
        created_by=staff.id,
    )
    session.add(release)
    await session.flush()
    await session.refresh(release)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="module_release.create",
        payload={"release_id": str(release.id), "version": release.version},
        ip=client_ip(request),
    )
    return await _release_out(session, release)


@router.get("/v1/admin/module-releases/{release_id}", response_model=ModuleReleaseOut)
async def admin_get_module_release(
    release_id: UUID, staff: StaffDep, session: StaffSession
) -> ModuleReleaseOut:
    release = await session.get(ModuleRelease, release_id)
    if release is None:
        raise ApiError("not_found", "release not found")
    return await _release_out(session, release)


@router.patch("/v1/admin/module-releases/{release_id}", response_model=ModuleReleaseOut)
async def admin_update_module_release(
    release_id: UUID,
    payload: ModuleReleaseUpdate,
    request: Request,
    staff: ReleaseAdminDep,
    session: StaffSession,
) -> ModuleReleaseOut:
    release = await session.get(ModuleRelease, release_id, with_for_update=True)
    if release is None:
        raise ApiError("not_found", "release not found")
    changes = payload.model_dump(exclude_unset=True)
    if "changelog_html" in changes and changes["changelog_html"] is not None:
        release.changelog_html, release.changelog_plain = releases.sanitize_changelog(
            changes.pop("changelog_html")
        )
    if "min_from_version" in changes:
        release.min_from_version = _check_metadata(changes.pop("min_from_version"))
    for field, value in changes.items():
        if value is not None or field in {"min_freepbx_major", "max_freepbx_major", "min_php_version"}:
            setattr(release, field, value)
    release.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="module_release.update",
        payload={"release_id": str(release_id), "fields": sorted(payload.model_fields_set)},
        ip=client_ip(request),
    )
    await session.flush()
    await session.refresh(release)
    return await _release_out(session, release)


@router.post("/v1/admin/module-releases/{release_id}/publish", response_model=ModuleReleaseOut)
async def admin_publish_module_release(
    release_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: ReleaseAdminDep,
    session: StaffSession,
) -> ModuleReleaseOut:
    # Code pushed to every customer PBX needs the operator's password (and TOTP when enabled).
    from app.routers.admin import _verify_sensitive_staff_action

    await _verify_sensitive_staff_action(session, staff, payload.current_password, payload.totp_code)
    release = await session.get(ModuleRelease, release_id, with_for_update=True)
    if release is None:
        raise ApiError("not_found", "release not found")
    if release.status == "published":
        return await _release_out(session, release)
    if not release.changelog_plain.strip():
        raise ApiError("invalid_request", "write a changelog before publishing")
    newest = _newest(await _published(session, release.product))
    if newest is not None and _key(release.version) <= _key(newest.version):
        raise ApiError(
            "invalid_request",
            f"version {release.version} must be newer than published {newest.version}",
        )
    now = datetime.now(UTC)
    release.status = "published"
    release.published_at = release.published_at or now
    release.updated_at = now
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="module_release.publish",
        payload={"release_id": str(release_id), "version": release.version},
        ip=client_ip(request),
    )
    await session.flush()
    await session.refresh(release)
    return await _release_out(session, release)


@router.post("/v1/admin/module-releases/{release_id}/revoke", response_model=ModuleReleaseOut)
async def admin_revoke_module_release(
    release_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: ReleaseAdminDep,
    session: StaffSession,
) -> ModuleReleaseOut:
    # Code pushed to every customer PBX needs the operator's password (and TOTP when enabled).
    from app.routers.admin import _verify_sensitive_staff_action

    await _verify_sensitive_staff_action(session, staff, payload.current_password, payload.totp_code)
    release = await session.get(ModuleRelease, release_id, with_for_update=True)
    if release is None:
        raise ApiError("not_found", "release not found")
    release.status = "revoked"
    release.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="module_release.revoke",
        payload={"release_id": str(release_id), "version": release.version},
        ip=client_ip(request),
    )
    await session.flush()
    await session.refresh(release)
    return await _release_out(session, release)


@router.delete("/v1/admin/module-releases/{release_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_module_release(
    release_id: UUID, request: Request, staff: ReleaseAdminDep, session: StaffSession
) -> None:
    release = await session.get(ModuleRelease, release_id, with_for_update=True)
    if release is None:
        raise ApiError("not_found", "release not found")
    if release.status != "draft":
        raise ApiError("invalid_request", "only drafts can be deleted; revoke published releases")
    await get_storage().delete(release.artifact_key)
    await session.delete(release)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="module_release.delete",
        payload={"release_id": str(release_id), "version": release.version},
        ip=client_ip(request),
    )


@router.get("/v1/admin/module-releases/{release_id}/download")
async def admin_download_module_release(
    release_id: UUID, staff: StaffDep, session: StaffSession
) -> StreamingResponse:
    release = await session.get(ModuleRelease, release_id)
    if release is None:
        raise ApiError("not_found", "release not found")
    return _download_response(release)


async def _installations_out(
    session: AsyncSession, rows: list[ModuleInstallation], tenant_names: dict[UUID, str]
) -> list[ModuleInstallationOut]:
    published = await _published(session, releases.PRODUCT_FREEPBX)
    items = []
    for row in rows:
        out = ModuleInstallationOut.model_validate(row)
        out.tenant_name = tenant_names.get(row.tenant_id)
        latest, _ = releases.select_update(
            published, row.module_version, freepbx=row.freepbx_version
        )
        out.update_available = latest is not None
        out.latest_version = latest.version if latest else None
        items.append(out)
    return items


@router.get("/v1/admin/module-installations")
async def admin_list_module_installations(
    staff: StaffDep,
    session: StaffSession,
    tenant_id: UUID | None = None,
    version: str | None = None,
    outdated: bool | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    query = select(ModuleInstallation, Tenant.name).join(
        Tenant, Tenant.id == ModuleInstallation.tenant_id
    )
    if tenant_id:
        query = query.where(ModuleInstallation.tenant_id == tenant_id)
    if version:
        query = query.where(ModuleInstallation.module_version == version)
    rows = (
        (await session.execute(query.order_by(ModuleInstallation.last_seen_at.desc())))
        .tuples()
        .all()
    )
    items = await _installations_out(
        session, [row for row, _ in rows], {row.tenant_id: name for row, name in rows}
    )
    if outdated is not None:
        items = [item for item in items if item.update_available == outdated]
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "next_cursor": str(offset + limit) if offset + limit < len(items) else None,
    }


@router.get("/v1/admin/module-installations/stats")
async def admin_module_installation_stats(staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(ModuleInstallation.module_version, func.count(ModuleInstallation.id))
                .where(ModuleInstallation.product == releases.PRODUCT_FREEPBX)
                .group_by(ModuleInstallation.module_version)
            )
        )
        .tuples()
        .all()
    )
    counts = sorted(
        ((str(version), int(count)) for version, count in rows),
        key=lambda item: releases.try_parse_version(item[0]) or (0, 0, 0),
        reverse=True,
    )
    failed = (
        await session.execute(
            select(func.count(ModuleInstallation.id)).where(
                ModuleInstallation.last_update_status.in_(("failed", "rolled_back"))
            )
        )
    ).scalar_one()
    newest = _newest(await _published(session, releases.PRODUCT_FREEPBX))
    return {
        "versions": [{"version": version, "count": count} for version, count in counts],
        "total": sum(count for _, count in counts),
        "latest_version": newest.version if newest else None,
        "failed_updates": int(failed),
    }


# --- FreePBX host: /v1/ingest/module ------------------------------------------


@router.get("/v1/ingest/module/updates", response_model=ModuleUpdateCheckOut)
async def ingest_module_updates(
    principal: ApiKeyDep,
    current: Annotated[str, Query(max_length=32)],
    host_uuid: Annotated[str, Query(min_length=8, max_length=64)],
    freepbx: Annotated[str | None, Query(max_length=64)] = None,
    php: Annotated[str | None, Query(max_length=32)] = None,
    hostname: Annotated[str | None, Query(max_length=255)] = None,
    service: Annotated[str | None, Query(max_length=32)] = None,
    channel: ModuleChannel = "stable",
) -> ModuleUpdateCheckOut:
    """Called on every module page load: records the host heartbeat and offers the next release."""
    assert principal.tenant_id is not None
    product = releases.PRODUCT_FREEPBX
    now = datetime.now(UTC)
    async with control_session_scope() as session:
        values = {
            "tenant_id": principal.tenant_id,
            "api_key_id": principal.id,
            "product": product,
            "host_uuid": host_uuid,
            "hostname": hostname,
            "freepbx_version": freepbx,
            "php_version": php,
            "module_version": current,
            "service_status": service,
            "last_seen_at": now,
        }
        await session.execute(
            pg_insert(ModuleInstallation)
            .values(**values)
            .on_conflict_do_update(
                constraint="module_installations_host_key",
                set_={
                    k: v
                    for k, v in values.items()
                    if k not in ("tenant_id", "product", "host_uuid")
                },
            )
        )
        published = await _published(session, product)
        revoked_current = (
            await session.execute(
                select(func.count())
                .select_from(ModuleRelease)
                .where(
                    ModuleRelease.product == product,
                    ModuleRelease.version == current,
                    ModuleRelease.status == "revoked",
                )
            )
        ).scalar_one() > 0
    latest, changelog = releases.select_update(
        published, current, freepbx=freepbx, php=php, channel=channel
    )
    manifest = releases.build_manifest(latest) if latest else None
    return ModuleUpdateCheckOut(
        current_revoked=revoked_current,
        update_available=latest is not None,
        current=current,
        latest=(
            ModuleUpdateOffer(
                id=latest.id,
                version=latest.version,
                severity=latest.severity,  # type: ignore[arg-type]
                title=latest.title,
                size=latest.artifact_size,
                sha256=latest.artifact_sha256,
                signature=latest.signature_b64,
                published_at=latest.published_at,
                manifest=manifest,
                manifest_signature=releases.sign_manifest(manifest) if manifest else None,
            )
            if latest
            else None
        ),
        changelog=[_entry(release) for release in changelog],
        server_time=now,
    )


@router.get("/v1/ingest/module/releases")
async def ingest_module_releases(principal: ApiKeyDep) -> dict[str, Any]:
    async with control_session_scope() as session:
        published = await _published(session, releases.PRODUCT_FREEPBX)
    published.sort(
        key=lambda row: (row.version_major, row.version_minor, row.version_patch), reverse=True
    )
    return {"items": [_entry(release) for release in published]}


@router.get("/v1/ingest/module/releases/{release_id}/download")
async def ingest_download_module_release(
    release_id: UUID, principal: ApiKeyDep
) -> StreamingResponse:
    async with control_session_scope() as session:
        release = await session.get(ModuleRelease, release_id)
    if release is None or release.status != "published":
        raise ApiError("not_found", "release not found")
    return _download_response(release)


@router.post("/v1/ingest/module/update-report", status_code=status.HTTP_202_ACCEPTED)
async def ingest_module_update_report(
    payload: ModuleUpdateReportIn, principal: ApiKeyDep
) -> dict[str, bool]:
    assert principal.tenant_id is not None
    now = datetime.now(UTC)
    async with control_session_scope() as session:
        installation = (
            await session.execute(
                select(ModuleInstallation).where(
                    ModuleInstallation.tenant_id == principal.tenant_id,
                    ModuleInstallation.product == releases.PRODUCT_FREEPBX,
                    ModuleInstallation.host_uuid == payload.host_uuid,
                )
            )
        ).scalar_one_or_none()
        if installation is None:
            raise ApiError("not_found", "unknown host; run an update check first")
        release_id = payload.release_id
        if release_id is not None and await session.get(ModuleRelease, release_id) is None:
            release_id = None
        session.add(
            ModuleUpdateEvent(
                tenant_id=principal.tenant_id,
                installation_id=installation.id,
                release_id=release_id,
                from_version=payload.from_version,
                to_version=payload.to_version,
                status=payload.status,
                message=payload.message,
            )
        )
        installation.last_update_status = payload.status
        installation.last_update_at = now
        installation.last_seen_at = now
        installation.last_update_error = (
            payload.message if payload.status in ("failed", "rolled_back") else None
        )
        if payload.status == "succeeded":
            installation.module_version = payload.to_version
    return {"accepted": True}


_CODE_RE = re.compile(r"^(SS-[A-Z]{3,4}-\d{4}|[a-z0-9_]{2,40})$")
MAX_DIAGNOSTICS_KEPT = 20


@router.post("/v1/ingest/module/diagnostics", status_code=status.HTTP_202_ACCEPTED)
async def ingest_module_diagnostics(
    payload: ModuleDiagnosticIn, principal: ApiKeyDep
) -> dict[str, bool]:
    """Doctor report from a FreePBX host: what is wrong there, with stable error codes."""
    assert principal.tenant_id is not None
    # Own bucket (not the call-upload budget): a host reports at most a dozen times per hour.
    await ratelimit.enforce(f"module-diag:{principal.tenant_id}:{payload.host_uuid}", 12, 3600)
    checks = [
        {
            "id": check.id,
            "status": check.status,
            "code": check.code if _CODE_RE.match(check.code) else "",
            "detail": sanitize_detail(check.detail, limit=300) or "",
        }
        for check in payload.checks
    ]
    codes = {c: n for c, n in payload.recent_codes.items() if _CODE_RE.match(c) and 0 <= n <= 10**7}
    first_failure = next((c["code"] for c in checks if c["status"] == "fail" and c["code"]), None)
    now = datetime.now(UTC)
    async with control_session_scope() as session:
        installation = (
            await session.execute(
                select(ModuleInstallation).where(
                    ModuleInstallation.tenant_id == principal.tenant_id,
                    ModuleInstallation.product == releases.PRODUCT_FREEPBX,
                    ModuleInstallation.host_uuid == payload.host_uuid,
                )
            )
        ).scalar_one_or_none()
        if installation is None:
            raise ApiError("not_found", "unknown host; run an update check first")
        installation.last_seen_at = now
        installation.asterisk_version = payload.asterisk_version
        installation.os_name = payload.os_name
        installation.last_error_code = first_failure
        session.add(
            ModuleDiagnostic(
                tenant_id=principal.tenant_id,
                installation_id=installation.id,
                module_version=payload.module_version,
                ok=payload.ok,
                failed_checks=payload.failed_checks,
                report={"checks": checks, "recent_codes": codes, "queue": payload.queue},
            )
        )
        await session.flush()
        stale = (
            await session.execute(
                select(ModuleDiagnostic.id)
                .where(ModuleDiagnostic.installation_id == installation.id)
                .order_by(ModuleDiagnostic.created_at.desc())
                .offset(MAX_DIAGNOSTICS_KEPT)
            )
        ).scalars().all()
        if stale:
            await session.execute(delete(ModuleDiagnostic).where(ModuleDiagnostic.id.in_(stale)))
    return {"accepted": True}


@router.get(
    "/v1/admin/module-installations/{installation_id}/diagnostics",
    response_model=list[ModuleDiagnosticOut],
)
async def admin_module_diagnostics(
    installation_id: UUID, _: StaffDep, session: StaffSession
) -> list[ModuleDiagnostic]:
    rows = (
        await session.execute(
            select(ModuleDiagnostic)
            .where(ModuleDiagnostic.installation_id == installation_id)
            .order_by(ModuleDiagnostic.created_at.desc())
            .limit(MAX_DIAGNOSTICS_KEPT)
        )
    ).scalars()
    return list(rows)


# --- tenant panel: /v1/module ----------------------------------------------------


@router.get("/v1/module/releases")
async def tenant_module_releases(principal: UserDep) -> dict[str, Any]:
    async with control_session_scope() as session:
        published = await _published(session, releases.PRODUCT_FREEPBX)
    published.sort(
        key=lambda row: (row.version_major, row.version_minor, row.version_patch), reverse=True
    )
    return {"items": [_entry(release) for release in published]}


@router.get("/v1/module/installations")
async def tenant_module_installations(principal: OrgAdminDep) -> dict[str, Any]:
    assert principal.tenant_id is not None
    async with control_session_scope() as session:
        rows = list(
            (
                await session.execute(
                    select(ModuleInstallation)
                    .where(
                        ModuleInstallation.tenant_id == principal.tenant_id,
                        ModuleInstallation.product == releases.PRODUCT_FREEPBX,
                    )
                    .order_by(ModuleInstallation.last_seen_at.desc())
                )
            )
            .scalars()
            .all()
        )
        items = await _installations_out(session, rows, {})
        newest = _newest(await _published(session, releases.PRODUCT_FREEPBX))
    return {
        "items": items,
        "latest": _entry(newest) if newest else None,
        "outdated": sum(1 for item in items if item.update_available),
    }
