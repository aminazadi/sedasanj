"""Jalase-Negar download dialog: store links, Windows/macOS installers, public overview."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.db import control_session_scope
from app.deps import StaffDep, StaffSession, SuperAdminDep, client_ip
from app.errors import ApiError
from app.models import JalaseNegarDesktopBuild, JalaseNegarRelease
from app.services import audit, ratelimit
from app.services import jalase_negar_downloads as downloads
from app.services.storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["jalase-negar downloads"])

_NO_STORE = {"Cache-Control": "no-store"}
_MIME = "application/octet-stream"


class DesktopBuildOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    platform: str
    version_name: str
    file_name: str
    artifact_sha256: str
    artifact_size: int
    created_at: datetime


async def _spool(upload: UploadFile) -> tuple[Path, str, int]:
    limit = get_settings().max_jalase_negar_desktop_bytes
    digest = hashlib.sha256()
    written = 0
    with tempfile.NamedTemporaryFile(prefix="jalase-negar-desktop-", delete=False) as handle:
        path = Path(handle.name)
        try:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise ApiError(
                        "archive_too_large",
                        f"the installer is larger than {limit // (1024 * 1024)} MiB; shrink it",
                    )
                digest.update(chunk)
                handle.write(chunk)
        except BaseException:
            handle.close()
            path.unlink(missing_ok=True)
            raise
    if written == 0:
        path.unlink(missing_ok=True)
        raise ApiError("invalid_request", "the installer file is empty; choose the file again")
    return path, digest.hexdigest(), written


# --- staff -----------------------------------------------------------------------------------


@router.get("/v1/admin/jalase-negar/store-links")
async def admin_read_links(session: StaffSession, _: StaffDep) -> dict[str, str]:
    return (await downloads.load_links(session)).model_dump()


@router.put("/v1/admin/jalase-negar/store-links")
async def admin_save_links(
    payload: downloads.StoreLinks,
    request: Request,
    session: StaffSession,
    principal: SuperAdminDep,
) -> dict[str, str]:
    await downloads.save_links(session, payload)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=principal.id,
        action="jalase_negar.store_links_update",
        payload={"stores": sorted(k for k, v in payload.model_dump().items() if v)},
        ip=client_ip(request),
    )
    return payload.model_dump()


@router.get("/v1/admin/jalase-negar/desktop-builds")
async def admin_list_builds(session: StaffSession, _: StaffDep) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(JalaseNegarDesktopBuild).order_by(JalaseNegarDesktopBuild.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [DesktopBuildOut.model_validate(row) for row in rows]}


@router.post(
    "/v1/admin/jalase-negar/desktop-builds",
    response_model=DesktopBuildOut,
    status_code=status.HTTP_201_CREATED,
)
async def admin_upload_build(
    request: Request,
    session: StaffSession,
    staff: SuperAdminDep,
    file: Annotated[UploadFile, File()],
    platform: Annotated[str, Form(max_length=8)],
    version: Annotated[str, Form(max_length=32)],
) -> DesktopBuildOut:
    version, file_name = downloads.validate_upload(platform, version, file.filename or "")
    path, sha256, size = await _spool(file)
    build_id = uuid4()
    key = downloads.artifact_key(build_id, file_name)
    try:
        try:
            await get_storage().put_path(key, path, content_type=_MIME)
        except Exception as error:  # noqa: BLE001
            raise ApiError(
                "release_file_unavailable",
                "the file store rejected the upload; nothing was saved, upload the file again",
            ) from error
    finally:
        path.unlink(missing_ok=True)
    build = JalaseNegarDesktopBuild(
        id=build_id,
        platform=platform,
        version_name=version,
        file_name=file_name,
        artifact_key=key,
        artifact_sha256=sha256,
        artifact_size=size,
        created_by=staff.id,
    )
    session.add(build)
    await session.flush()
    await session.refresh(build)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="jalase_negar_desktop_build.create",
        payload={"build_id": str(build_id), "platform": platform, "version": version},
        ip=client_ip(request),
    )
    return DesktopBuildOut.model_validate(build)


@router.delete(
    "/v1/admin/jalase-negar/desktop-builds/{build_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def admin_delete_build(build_id: UUID, request: Request, staff: SuperAdminDep) -> None:
    async with control_session_scope() as session:
        build = await session.get(JalaseNegarDesktopBuild, build_id, with_for_update=True)
        if build is None:
            raise ApiError("not_found", "installer not found; refresh the list")
        key = build.artifact_key
        await session.delete(build)
        await audit.record(
            session,
            actor_type="staff",
            actor_id=staff.id,
            action="jalase_negar_desktop_build.delete",
            payload={"build_id": str(build_id), "platform": build.platform},
            ip=client_ip(request),
        )
    try:
        await get_storage().delete(key)
    except Exception:  # noqa: BLE001 - an orphan file is harmless; the row is already gone
        logger.warning("jalase_negar_desktop_cleanup_deferred build_id=%s", build_id)


# --- public ----------------------------------------------------------------------------------


def _desktop(build: JalaseNegarDesktopBuild | None) -> dict[str, Any] | None:
    if build is None:
        return None
    return {
        "version": build.version_name,
        "size": build.artifact_size,
        "sha256": build.artifact_sha256,
        "download_path": f"/v1/jalase-negar/desktop/{build.id}/download",
    }


@router.get("/v1/jalase-negar/downloads")
async def public_downloads(request: Request, response: Response) -> dict[str, Any]:
    """Everything the landing-page dialog lists: Android APK, Windows, macOS and store links."""
    response.headers.update(_NO_STORE)
    await ratelimit.enforce(f"jalase-negar-downloads:{client_ip(request)}", 60, 60)
    async with control_session_scope() as session:
        apk = (
            (
                await session.execute(
                    select(JalaseNegarRelease)
                    .where(
                        JalaseNegarRelease.status == "published",
                        JalaseNegarRelease.channel == "stable",
                        JalaseNegarRelease.rollout_percent == 100,
                    )
                    .order_by(JalaseNegarRelease.version_code.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        builds = list((await session.execute(select(JalaseNegarDesktopBuild))).scalars().all())
        links = await downloads.load_links(session)
    latest = downloads.latest_per_platform(builds)
    return {
        "android": None
        if apk is None
        else {
            "version": apk.version_name,
            "size": apk.artifact_size,
            "sha256": apk.artifact_sha256,
            "download_path": f"/v1/jalase-negar/android/releases/{apk.id}/download",
        },
        "windows": _desktop(latest.get("windows")),
        "macos": _desktop(latest.get("macos")),
        "stores": {name: url for name, url in links.model_dump().items() if url},
    }


@router.get("/v1/jalase-negar/desktop/{build_id}/download")
async def download_build(request: Request, build_id: UUID) -> StreamingResponse:
    await ratelimit.enforce(f"jalase-negar-desktop-dl:{client_ip(request)}", 30, 60)
    async with control_session_scope() as session:
        build = await session.get(JalaseNegarDesktopBuild, build_id)
    if build is None:
        raise ApiError("not_found", "this installer is no longer available; reload the page")
    storage = get_storage()
    try:
        present = await storage.exists(build.artifact_key)
    except Exception as error:  # noqa: BLE001
        raise ApiError(
            "release_file_unavailable",
            "the file is temporarily unavailable; try again in a few minutes",
        ) from error
    if not present:
        raise ApiError(
            "release_file_unavailable",
            "the file is missing from storage; ask support to re-upload this installer",
        )
    return StreamingResponse(
        storage.iter_chunks(build.artifact_key),
        media_type=_MIME,
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(build.artifact_size),
            "ETag": f'"{build.artifact_sha256}"',
            "Content-Disposition": f'attachment; filename="{build.file_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
