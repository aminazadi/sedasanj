"""Jalase-Negar Android releases: staff publishing and the app's in-app update check."""

from __future__ import annotations

import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import control_session_scope
from app.deps import Principal, StaffDep, StaffSession, client_ip, require_staff_roles
from app.errors import ApiError
from app.metrics import (
    jalase_negar_download_total,
    jalase_negar_update_checks_total,
    jalase_negar_update_install_total,
)
from app.models import JalaseNegarRelease
from app.schemas import (
    JalaseNegarInstallReportIn,
    JalaseNegarReleaseOut,
    JalaseNegarReleaseStatus,
    JalaseNegarReleaseUpdate,
    JalaseNegarUpdateCheckOut,
    JalaseNegarUpdateOffer,
    StaffSensitiveAction,
)
from app.services import audit, ratelimit
from app.services import jalase_negar_releases as apks
from app.services import module_releases as notes
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jalase-negar updates"])

ReleaseAdminDep = Annotated[Principal, Depends(require_staff_roles("super_admin"))]

_PUBLISH_LOCK = "jalase_negar_release_publish"
_NO_STORE = {"Cache-Control": "no-store"}


# --- helpers ----


async def _spool_upload(upload: UploadFile) -> Path:
    """Stream the multipart body to disk so a 200 MiB APK never sits in memory."""
    limit = get_settings().max_jalase_negar_apk_bytes
    written = 0
    with tempfile.NamedTemporaryFile(prefix="jalase-negar-", suffix=".apk", delete=False) as handle:
        path = Path(handle.name)
        try:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise ApiError(
                        "archive_too_large",
                        f"the APK is larger than {limit // (1024 * 1024)} MiB; shrink the build",
                    )
                handle.write(chunk)
        except BaseException:
            handle.close()
            path.unlink(missing_ok=True)
            raise
    return path


async def _get(
    session: AsyncSession, release_id: UUID, *, lock: bool = False
) -> JalaseNegarRelease:
    release = await session.get(JalaseNegarRelease, release_id, with_for_update=lock)
    if release is None:
        raise ApiError("not_found", "release not found")
    return release


async def _highest_code(
    session: AsyncSession, *, statuses: tuple[str, ...], exclude: UUID | None = None
) -> int:
    query = select(func.max(JalaseNegarRelease.version_code)).where(
        JalaseNegarRelease.status.in_(statuses)
    )
    if exclude is not None:
        query = query.where(JalaseNegarRelease.id != exclude)
    return int((await session.execute(query)).scalar_one() or 0)


def _version_conflict(code: int, highest: int) -> ApiError:
    return ApiError(
        "release_version_conflict",
        f"versionCode {code} must be higher than every earlier release ({highest}); "
        "raise the version in pubspec.yaml and build the APK again",
    )


async def sweep_orphan_files(limit: int = 200) -> int:
    """Delete stored APKs that no release row refers to, after the safe grace period."""
    storage = get_storage()
    stored = await storage.list_keys(apks.KEY_PREFIX)
    if not stored:
        return 0
    async with control_session_scope() as session:
        rows = (await session.execute(select(JalaseNegarRelease.id))).scalars().all()
    removed = 0
    for key in apks.orphan_keys(stored, set(rows))[:limit]:
        try:
            await storage.delete(key)
            removed += 1
        except Exception:  # noqa: BLE001 - try again on the next sweep
            logger.warning("jalase_negar_apk_sweep_failed key=%s", key)
    return removed


def _download_headers(release: JalaseNegarRelease) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Accept-Ranges": "bytes",
        "ETag": f'"{release.artifact_sha256}"',
        "Content-Disposition": f'attachment; filename="jalase-negar-{release.version_name}.apk"',
        "X-Content-Type-Options": "nosniff",
    }


async def _apk_response(
    release: JalaseNegarRelease, range_header: str | None, if_range: str | None
) -> StreamingResponse:
    storage = get_storage()
    try:
        present = await storage.exists(release.artifact_key)
    except Exception as error:  # noqa: BLE001
        jalase_negar_download_total.labels(result="unavailable").inc()
        raise ApiError(
            "release_file_unavailable",
            "the update file is temporarily unavailable; try again in a few minutes",
        ) from error
    if not present:
        jalase_negar_download_total.labels(result="unavailable").inc()
        raise ApiError(
            "release_file_unavailable",
            "the update file is missing from storage; ask support to re-upload this release",
        )
    headers = _download_headers(release)
    size = release.artifact_size
    window: tuple[int, int] | None = None
    if range_header and (if_range is None or if_range.strip('"') == release.artifact_sha256):
        window = apks.parse_range(range_header, size)
        if window is None:
            jalase_negar_download_total.labels(result="range_invalid").inc()
            return Response(  # type: ignore[return-value]
                status_code=416,
                headers={**headers, "Content-Range": f"bytes */{size}"},
            )
    if window is None:
        jalase_negar_download_total.labels(result="ok").inc()
        return StreamingResponse(
            storage.iter_chunks(release.artifact_key),
            media_type=apks.APK_MIME,
            headers={**headers, "Content-Length": str(size)},
        )
    first, last = window
    jalase_negar_download_total.labels(result="partial").inc()
    return StreamingResponse(
        storage.iter_chunks(release.artifact_key, byte_range=(first, last)),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=apks.APK_MIME,
        headers={
            **headers,
            "Content-Length": str(last - first + 1),
            "Content-Range": f"bytes {first}-{last}/{size}",
        },
    )


# --- staff: /v1/admin/jalase-negar/releases ----


@router.get("/v1/admin/jalase-negar/releases")
async def admin_list_releases(
    staff: StaffDep,
    session: StaffSession,
    status_filter: Annotated[JalaseNegarReleaseStatus | None, Query(alias="status")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> dict[str, Any]:
    query = select(JalaseNegarRelease)
    if status_filter:
        query = query.where(JalaseNegarRelease.status == status_filter)
    total = int(
        (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    )
    rows = (
        (
            await session.execute(
                query.order_by(JalaseNegarRelease.version_code.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    latest = (
        await session.execute(
            select(func.max(JalaseNegarRelease.version_code)).where(
                JalaseNegarRelease.status == "published"
            )
        )
    ).scalar_one()
    return {
        "items": [JalaseNegarReleaseOut.model_validate(row) for row in rows],
        "total": total,
        "latest_published_code": int(latest) if latest is not None else None,
        "next_cursor": str(offset + limit) if offset + len(rows) < total else None,
    }


@router.post(
    "/v1/admin/jalase-negar/releases",
    response_model=JalaseNegarReleaseOut,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_release(
    request: Request,
    staff: ReleaseAdminDep,
    session: StaffSession,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=200)] = None,
    changelog_html: Annotated[str, Form(max_length=200_000)] = "",
) -> JalaseNegarReleaseOut:
    path = await _spool_upload(file)
    release_id = uuid4()
    try:
        inspection = await apks.inspect_apk(path)
        taken = (
            await session.execute(
                select(JalaseNegarRelease.version_code, JalaseNegarRelease.version_name).where(
                    (JalaseNegarRelease.version_code == inspection.version_code)
                    | (JalaseNegarRelease.version_name == inspection.version_name)
                )
            )
        ).first()
        if taken is not None:
            raise ApiError(
                "release_version_conflict",
                f"version {inspection.version_name} ({inspection.version_code}) is already "
                "registered; raise the version and build the APK again",
            )
        highest = await _highest_code(session, statuses=("published", "revoked"))
        if inspection.version_code <= highest:
            raise _version_conflict(inspection.version_code, highest)
        safe_html, plain = notes.sanitize_changelog(changelog_html)
        key = apks.artifact_key(release_id, inspection.version_name)
        try:
            await get_storage().put_path(key, path, content_type=apks.APK_MIME)
        except Exception as error:  # noqa: BLE001
            raise ApiError(
                "release_file_unavailable",
                "the file store rejected the upload; nothing was saved, upload the APK again",
            ) from error
    finally:
        path.unlink(missing_ok=True)
    release = JalaseNegarRelease(
        id=release_id,
        package_name=inspection.package_name,
        version_name=inspection.version_name,
        version_code=inspection.version_code,
        min_sdk=inspection.min_sdk,
        abis=list(inspection.abis),
        title=(title or "").strip() or f"نسخهٔ {inspection.version_name}",
        changelog_html=safe_html,
        changelog_plain=plain,
        artifact_key=key,
        artifact_sha256=inspection.sha256,
        artifact_size=inspection.size,
        signing_cert_sha256=inspection.cert_sha256,
        status="draft",
        created_by=staff.id,
    )
    session.add(release)
    try:
        await session.flush()
    except IntegrityError as error:
        await get_storage().delete(key)
        raise ApiError(
            "release_version_conflict",
            "this version was registered at the same moment; refresh the list",
        ) from error
    await session.refresh(release)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="jalase_negar_release.create",
        payload={
            "release_id": str(release.id),
            "version": release.version_name,
            "version_code": release.version_code,
        },
        ip=client_ip(request),
    )
    return JalaseNegarReleaseOut.model_validate(release)


@router.get("/v1/admin/jalase-negar/releases/{release_id}", response_model=JalaseNegarReleaseOut)
async def admin_get_release(
    release_id: UUID, staff: StaffDep, session: StaffSession
) -> JalaseNegarReleaseOut:
    return JalaseNegarReleaseOut.model_validate(await _get(session, release_id))


@router.patch("/v1/admin/jalase-negar/releases/{release_id}", response_model=JalaseNegarReleaseOut)
async def admin_update_release(
    release_id: UUID,
    payload: JalaseNegarReleaseUpdate,
    request: Request,
    staff: ReleaseAdminDep,
    session: StaffSession,
) -> JalaseNegarReleaseOut:
    release = await _get(session, release_id, lock=True)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("title") is not None:
        release.title = changes["title"].strip()
    if changes.get("changelog_html") is not None:
        release.changelog_html, release.changelog_plain = notes.sanitize_changelog(
            changes["changelog_html"]
        )
        if release.status == "published" and not release.changelog_plain.strip():
            raise ApiError("invalid_request", "a published release needs release notes")
    if changes.get("rollout_percent") is not None:
        release.rollout_percent = changes["rollout_percent"]
    if changes.get("min_supported_version_code") is not None:
        floor = changes["min_supported_version_code"]
        if floor > release.version_code:
            raise ApiError(
                "invalid_request",
                "the minimum supported build cannot exceed this release's own build number",
            )
        release.min_supported_version_code = floor
    if changes.get("channel") is not None:
        release.channel = changes["channel"]
    release.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="jalase_negar_release.update",
        payload={"release_id": str(release_id), "fields": sorted(payload.model_fields_set)},
        ip=client_ip(request),
    )
    await session.flush()
    await session.refresh(release)
    return JalaseNegarReleaseOut.model_validate(release)


@router.get("/v1/admin/jalase-negar/releases/{release_id}/download")
async def admin_download_release(
    release_id: UUID, staff: StaffDep, session: StaffSession
) -> StreamingResponse:
    release = await _get(session, release_id)
    return await _apk_response(release, None, None)


@router.post(
    "/v1/admin/jalase-negar/releases/{release_id}/publish", response_model=JalaseNegarReleaseOut
)
async def admin_publish_release(
    release_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: ReleaseAdminDep,
    session: StaffSession,
) -> JalaseNegarReleaseOut:
    from app.routers.admin import _verify_sensitive_staff_action

    await _verify_sensitive_staff_action(
        session, staff, payload.current_password, payload.totp_code
    )
    # One publisher at a time: the versionCode comparison below must see every committed
    # publication, so concurrent requests queue here until the earlier transaction commits.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": _PUBLISH_LOCK}
    )
    release = await _get(session, release_id, lock=True)
    if release.status == "published":
        return JalaseNegarReleaseOut.model_validate(release)
    if release.status == "revoked":
        raise ApiError(
            "release_version_conflict",
            "a revoked release cannot be published again; build a new version",
        )
    if not release.changelog_plain.strip():
        raise ApiError("invalid_request", "write release notes before publishing")
    highest = await _highest_code(session, statuses=("published", "revoked"), exclude=release.id)
    if release.version_code <= highest:
        raise _version_conflict(release.version_code, highest)
    if not await get_storage().exists(release.artifact_key):
        raise ApiError(
            "release_file_unavailable",
            "the APK file is missing from storage; delete this draft and upload it again",
        )
    now = datetime.now(UTC)
    release.status = "published"
    release.published_at = now
    release.updated_at = now
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="jalase_negar_release.publish",
        payload={
            "release_id": str(release_id),
            "version": release.version_name,
            "version_code": release.version_code,
        },
        ip=client_ip(request),
    )
    await session.flush()
    await session.refresh(release)
    return JalaseNegarReleaseOut.model_validate(release)


@router.post(
    "/v1/admin/jalase-negar/releases/{release_id}/revoke", response_model=JalaseNegarReleaseOut
)
async def admin_revoke_release(
    release_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: ReleaseAdminDep,
    session: StaffSession,
) -> JalaseNegarReleaseOut:
    from app.routers.admin import _verify_sensitive_staff_action

    await _verify_sensitive_staff_action(
        session, staff, payload.current_password, payload.totp_code
    )
    release = await _get(session, release_id, lock=True)
    if release.status == "draft":
        raise ApiError("invalid_request", "a draft is not published; delete it instead")
    if release.status == "published":
        now = datetime.now(UTC)
        release.status = "revoked"
        release.revoked_at = now
        release.updated_at = now
        await audit.record(
            session,
            actor_type="staff",
            actor_id=staff.id,
            action="jalase_negar_release.revoke",
            payload={
                "release_id": str(release_id),
                "version": release.version_name,
                "version_code": release.version_code,
            },
            ip=client_ip(request),
        )
        await session.flush()
        await session.refresh(release)
    return JalaseNegarReleaseOut.model_validate(release)


@router.delete(
    "/v1/admin/jalase-negar/releases/{release_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def admin_delete_release(release_id: UUID, request: Request, staff: ReleaseAdminDep) -> None:
    # Own transaction on purpose: access is closed and committed in the database first, and only
    # then is the file removed. A failed file removal is repeated by the periodic sweeper.
    async with control_session_scope() as session:
        release = await _get(session, release_id, lock=True)
        if release.status != "draft":
            raise ApiError(
                "invalid_request", "only drafts can be deleted; revoke published releases"
            )
        key = release.artifact_key
        version = release.version_name
        await session.delete(release)
        await audit.record(
            session,
            actor_type="staff",
            actor_id=staff.id,
            action="jalase_negar_release.delete",
            payload={"release_id": str(release_id), "version": version},
            ip=client_ip(request),
        )
    try:
        await get_storage().delete(key)
    except Exception:  # noqa: BLE001 - the sweeper retries once the grace period has passed
        logger.warning("jalase_negar_apk_cleanup_deferred release_id=%s", release_id)


# --- the app: /v1/jalase-negar/android ----


@router.get("/v1/jalase-negar/android/update", response_model=JalaseNegarUpdateCheckOut)
async def check_for_update(
    request: Request,
    response: Response,
    version_code: Annotated[int, Query(ge=1, le=2_100_000_000)],
    sdk_int: Annotated[int, Query(ge=1, le=100)],
    abis: Annotated[str, Query(max_length=200)] = "",
    cert_sha256: Annotated[str, Query(max_length=95)] = "",
    install_id: Annotated[str, Query(max_length=64)] = "",
    channel: Annotated[Literal["stable", "beta"], Query()] = "stable",
) -> JalaseNegarUpdateCheckOut:
    response.headers.update(_NO_STORE)
    await ratelimit.enforce(f"jalase-negar-update:{client_ip(request)}", 60, 60)
    device_abis = apks.parse_abis(abis)
    cert = apks.normalize_cert(cert_sha256)
    async with control_session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(JalaseNegarRelease).where(JalaseNegarRelease.status == "published")
                )
            )
            .scalars()
            .all()
        )
    chosen = apks.select_update(
        list(rows),
        version_code=version_code,
        sdk_int=sdk_int,
        abis=device_abis,
        cert_sha256=cert,
        install_id=apks.normalize_install_id(install_id),
        channel=channel,
    )
    if chosen is None:
        jalase_negar_update_checks_total.labels(result="none").inc()
        return JalaseNegarUpdateCheckOut(update=None)
    jalase_negar_update_checks_total.labels(result="offered").inc()
    return JalaseNegarUpdateCheckOut(
        update=JalaseNegarUpdateOffer(
            id=chosen.id,
            version=chosen.version_name,
            version_code=chosen.version_code,
            title=chosen.title,
            notes=chosen.changelog_plain,
            size=chosen.artifact_size,
            sha256=chosen.artifact_sha256,
            min_sdk=chosen.min_sdk,
            published_at=chosen.published_at,
            download_path=f"/v1/jalase-negar/android/releases/{chosen.id}/download",
            mandatory=apks.is_mandatory(chosen, version_code),
        )
    )


@router.post("/v1/jalase-negar/android/update/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_install_result(request: Request, payload: JalaseNegarInstallReportIn) -> None:
    """Anonymous outcome of an automatic update attempt, to spot phones that block silent installs.

    Nothing is stored: only counters move and one log line is written, with no IP or identity.
    """
    await ratelimit.enforce(f"jalase-negar-update-report:{client_ip(request)}", 30, 60)
    if payload.result == "failed" and payload.error_code is None:
        raise ApiError("invalid_request", "a failed report needs an error_code")
    jalase_negar_update_install_total.labels(
        result=payload.result,
        error_code=payload.error_code or "none",
        silent="true" if payload.silent else "false",
    ).inc()
    logger.info(
        "jalase_negar_update_install result=%s code=%s sdk=%s maker=%s silent=%s",
        payload.result,
        payload.error_code or "-",
        payload.sdk_int,
        payload.manufacturer.lower()[:32] or "-",
        payload.silent,
    )


@router.get("/v1/jalase-negar/android/releases/{release_id}/download")
async def download_release(request: Request, release_id: UUID) -> StreamingResponse:
    await ratelimit.enforce(f"jalase-negar-download:{client_ip(request)}", 60, 60)
    async with control_session_scope() as session:
        release = await session.get(JalaseNegarRelease, release_id)
    # Checked on every request: a revoked release stops serving at once, even mid-download.
    if release is None or release.status != "published":
        jalase_negar_download_total.labels(result="not_found").inc()
        raise ApiError("not_found", "this update is no longer available; check for updates again")
    return await _apk_response(
        release, request.headers.get("range"), request.headers.get("if-range")
    )
