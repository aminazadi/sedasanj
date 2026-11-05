"""ML model registry: machine upload by the GPU publisher key, staff list/download/admin actions."""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
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
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import control_session_scope
from app.deps import (
    Principal,
    StaffDep,
    StaffSession,
    client_ip,
    require_scope,
    require_staff_roles,
)
from app.errors import ApiError
from app.metrics import ml_model_events_total
from app.models import ApiKey, MlModelRelease
from app.schemas import (
    MlModelChannel,
    MlModelMetadata,
    MlModelOut,
    MlModelPinRequest,
    MlModelPublishOut,
    MlModelRolloutRequest,
    MlModelStatus,
    StaffSensitiveAction,
)
from app.services import audit, ml_models, ratelimit
from app.services import jalase_negar_releases as http_ranges
from app.services.api_scopes import ML_PUBLISH_SCOPE
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ml models"])

MlAdminDep = Annotated[Principal, Depends(require_staff_roles("super_admin"))]
MlPublishDep = Annotated[Principal, Depends(require_scope(ML_PUBLISH_SCOPE))]

_SAFE_NAME = re.compile(r"[^0-9A-Za-z._+-]")


# --- helpers ----


async def _verify_sensitive(
    session: AsyncSession, staff: Principal, body: StaffSensitiveAction
) -> None:
    from app.routers.admin import _verify_sensitive_staff_action

    await _verify_sensitive_staff_action(session, staff, body.current_password, body.totp_code)


async def _get(session: AsyncSession, model_id: UUID, *, lock: bool = False) -> MlModelRelease:
    row = await session.get(MlModelRelease, model_id, with_for_update=lock)
    if row is None:
        raise ApiError("ml_model_not_found", "this model does not exist; refresh the model list")
    return row


async def _kind_lock(session: AsyncSession, kind: str) -> None:
    """Serialise publishing and promotion per kind so `latest` keeps exactly one copy."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": f"ml_model:{kind}"}
    )


def retire_previous(rows: list[MlModelRelease], *, channel: str, now: datetime) -> list[str]:
    """Mark replaced rows and return the storage keys to delete right away."""
    keys: list[str] = []
    retention = get_settings().ml_model_prev_retention_hours
    for old in rows:
        if channel == "latest":
            old.status, old.deleted_at = "deleted", now
            keys.append(old.artifact_key)
            continue
        old.superseded_at = now
        if retention == 0 and not old.pinned:
            old.status, old.deleted_at = "deleted", now
            keys.append(old.artifact_key)
    return keys


async def _previous(
    session: AsyncSession, *, kind: str, channel: str, exclude: UUID
) -> list[MlModelRelease]:
    return list(
        (
            await session.execute(
                select(MlModelRelease)
                .where(
                    MlModelRelease.kind == kind,
                    MlModelRelease.channel == channel,
                    MlModelRelease.status == "ready",
                    MlModelRelease.superseded_at.is_(None),
                    MlModelRelease.id != exclude,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )


async def _deny_publish(request: Request, principal: Principal, reason: str) -> ApiError:
    async with control_session_scope() as session:
        await audit.record(
            session,
            actor_type="api_key",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="ml_model.publish_denied",
            payload={"reason": reason},
            ip=client_ip(request),
        )
    ml_model_events_total.labels(action="publish", result="forbidden").inc()
    return ApiError(
        "ml_publish_forbidden",
        "this key may not publish models; create a publisher key with "
        "scripts/create_ml_publisher_key.py for the platform tenant and restrict it to the "
        "GPU server addresses",
    )


async def _assert_publisher(request: Request, principal: Principal) -> None:
    settings = get_settings()
    if settings.ml_publisher_tenant_id is None:
        raise await _deny_publish(request, principal, "publishing_not_configured")
    if (
        principal.key_kind != "integration"
        or principal.tenant_id != settings.ml_publisher_tenant_id
    ):
        raise await _deny_publish(request, principal, "wrong_key_or_tenant")
    async with control_session_scope() as session:
        cidrs = (
            await session.execute(select(ApiKey.allowed_cidrs).where(ApiKey.id == principal.id))
        ).scalar_one_or_none()
    # The address list is enforced by current_api_key; an empty list would mean "anywhere".
    if not cidrs:
        raise await _deny_publish(request, principal, "ip_allowlist_empty")


async def _spool(upload: UploadFile) -> tuple[Path, str, int]:
    """Stream the body to disk while hashing it; refuse empty, oversized or non-ONNX files."""
    limit = get_settings().max_ml_model_bytes
    digest = hashlib.sha256()
    written = 0
    first = b""
    with tempfile.NamedTemporaryFile(prefix="ml-model-", suffix=".onnx", delete=False) as handle:
        path = Path(handle.name)
        try:
            while chunk := await upload.read(1024 * 1024):
                if not first:
                    first = chunk[:1]
                written += len(chunk)
                if written > limit:
                    raise ApiError(
                        "ml_model_invalid",
                        f"the model is larger than {limit // (1024 * 1024)} MiB; "
                        "export a smaller model",
                    )
                digest.update(chunk)
                handle.write(chunk)
        except BaseException:
            handle.close()
            path.unlink(missing_ok=True)
            raise
    if written == 0 or first[0] != ml_models.ONNX_FIRST_BYTE:
        path.unlink(missing_ok=True)
        raise ApiError("ml_model_invalid", "the file is not an ONNX model; export it again")
    return path, digest.hexdigest(), written


def _parse_metadata(raw: str) -> MlModelMetadata:
    try:
        return MlModelMetadata.model_validate_json(raw)
    except ValidationError as error:
        fields = ", ".join(
            sorted({".".join(str(p) for p in e["loc"]) or "metadata" for e in error.errors()})
        )
        raise ApiError(
            "ml_model_invalid", f"invalid model metadata ({fields}); fix these fields"
        ) from error


async def _stored_hash(key: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    async for chunk in get_storage().iter_chunks(key):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _download_headers(row: MlModelRelease) -> dict[str, str]:
    name = _SAFE_NAME.sub("_", f"{row.kind}-{row.version}.onnx")
    return {
        "Cache-Control": "no-store",
        "Accept-Ranges": "bytes",
        "ETag": f'"{row.sha256}"',
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Content-Type-Options": "nosniff",
    }


# --- publisher: POST /v1/ml/models ----


@router.post("/v1/ml/models", response_model=MlModelPublishOut)
async def publish_model(
    request: Request,
    response: Response,
    principal: MlPublishDep,
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form(max_length=40_000)],
    channel: Annotated[MlModelChannel, Query()] = "latest",
) -> MlModelPublishOut:
    settings = get_settings()
    await _assert_publisher(request, principal)
    await ratelimit.enforce(f"ml-publish:{principal.id}", settings.ml_publish_per_hour, 3600)
    meta = _parse_metadata(metadata)
    path, digest, size = await _spool(file)
    try:
        if digest != meta.sha256:
            ml_model_events_total.labels(action="publish", result="checksum_mismatch").inc()
            raise ApiError(
                "ml_model_checksum_mismatch",
                "the uploaded file's SHA-256 differs from the declared one; compute it again "
                "and upload the file again",
            )
        existing = await _claim(meta, channel, size, digest, principal)
        if isinstance(existing, MlModelRelease):
            return MlModelPublishOut.model_validate(existing, from_attributes=True).model_copy(
                update={"already_published": True}
            )
        row_id, key = existing
        storage = get_storage()
        try:
            await storage.put_path(key, path, content_type=ml_models.ONNX_MIME)
            stored_digest, stored_size = await _stored_hash(key)
        except Exception as error:  # noqa: BLE001
            await _abandon(row_id, key)
            raise ApiError(
                "release_file_unavailable",
                "the file store rejected the upload; nothing was saved, upload the model again",
            ) from error
        if stored_digest != digest or stored_size != size:
            await _abandon(row_id, key)
            raise ApiError(
                "ml_model_checksum_mismatch",
                "the stored copy does not match the uploaded file; upload the model again",
            )
    finally:
        path.unlink(missing_ok=True)
    row, doomed = await _finalize(row_id, channel, request, principal)
    await ml_models.delete_keys(doomed)
    ml_model_events_total.labels(action="publish", result="ok").inc()
    response.status_code = status.HTTP_201_CREATED
    return MlModelPublishOut.model_validate(row, from_attributes=True)


async def _claim(
    meta: MlModelMetadata, channel: str, size: int, digest: str, principal: Principal
) -> MlModelRelease | tuple[UUID, str]:
    """Idempotency on (kind, version): same content returns the row, other content conflicts."""
    async with control_session_scope() as session:
        await _kind_lock(session, meta.kind)
        found = (
            await session.execute(
                select(MlModelRelease)
                .where(MlModelRelease.kind == meta.kind, MlModelRelease.version == meta.version)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if found is not None:
            if found.sha256 != digest:
                ml_model_events_total.labels(action="publish", result="conflict").inc()
                raise ApiError(
                    "ml_model_version_conflict",
                    f"version {meta.version} of {meta.kind} already exists with different "
                    "content; raise the version and upload again",
                )
            if found.status == "ready":
                ml_model_events_total.labels(action="publish", result="idempotent").inc()
                session.expunge(found)
                return found
            if found.status != "uploading":
                raise ApiError(
                    "ml_model_version_conflict",
                    f"version {meta.version} of {meta.kind} was retired; raise the version",
                )
            return found.id, found.artifact_key
        row_id = uuid4()
        key = ml_models.artifact_key(row_id, meta.kind, meta.version)
        session.add(
            MlModelRelease(
                id=row_id,
                kind=meta.kind,
                version=meta.version,
                channel=channel,
                status="uploading",
                artifact_key=key,
                sha256=digest,
                size_bytes=size,
                dim=meta.dim,
                sample_rate=meta.sample_rate,
                metrics=meta.metrics,
                dataset_manifest_hash=meta.dataset_manifest_hash,
                training_run_id=meta.training_run_id,
                signature=meta.signature,
                published_by_key=principal.id,
            )
        )
        try:
            await session.flush()
        except IntegrityError as error:
            raise ApiError(
                "ml_model_version_conflict",
                "this version was registered at the same moment; upload again to confirm",
            ) from error
        return row_id, key


async def _abandon(row_id: UUID, key: str) -> None:
    async with control_session_scope() as session:
        row = await session.get(MlModelRelease, row_id)
        if row is not None and row.status == "uploading":
            await session.delete(row)
    await ml_models.delete_keys([key])


async def _finalize(
    row_id: UUID, channel: str, request: Request, principal: Principal
) -> tuple[MlModelRelease, list[str]]:
    async with control_session_scope() as session:
        row = await _get(session, row_id, lock=True)
        await _kind_lock(session, row.kind)
        now = datetime.now(UTC)
        previous = await _previous(session, kind=row.kind, channel=channel, exclude=row.id)
        row.status, row.ready_at, row.channel = "ready", now, channel
        doomed = retire_previous(previous, channel=channel, now=now)
        await audit.record(
            session,
            actor_type="api_key",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="ml_model.publish",
            payload={
                "model_id": str(row.id),
                "kind": row.kind,
                "version": row.version,
                "channel": channel,
                "sha256": row.sha256,
                "replaced": [str(old.id) for old in previous],
            },
            ip=client_ip(request),
        )
        await session.flush()
        await session.refresh(row)
        session.expunge(row)
        return row, doomed


# --- staff: /v1/admin/ml/models ----


@router.get("/v1/admin/ml/models")
async def admin_list_models(
    staff: StaffDep,
    session: StaffSession,
    kind: Annotated[str | None, Query(max_length=64)] = None,
    channel: MlModelChannel | None = None,
    status_filter: Annotated[MlModelStatus | None, Query(alias="status")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    query = select(MlModelRelease)
    if kind:
        query = query.where(MlModelRelease.kind == kind)
    if channel:
        query = query.where(MlModelRelease.channel == channel)
    if status_filter:
        query = query.where(MlModelRelease.status == status_filter)
    total = int(
        (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    )
    rows = (
        (
            await session.execute(
                query.order_by(MlModelRelease.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    kinds = (
        (
            await session.execute(
                select(MlModelRelease.kind).distinct().order_by(MlModelRelease.kind)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [MlModelOut.model_validate(row) for row in rows],
        "total": total,
        "kinds": list(kinds),
        "prev_retention_hours": get_settings().ml_model_prev_retention_hours,
        "next_cursor": str(offset + limit) if offset + len(rows) < total else None,
    }


@router.get("/v1/admin/ml/models/{model_id}", response_model=MlModelOut)
async def admin_get_model(model_id: UUID, staff: StaffDep, session: StaffSession) -> MlModelOut:
    return MlModelOut.model_validate(await _get(session, model_id))


@router.get("/v1/admin/ml/models/{model_id}/download")
async def admin_download_model(
    request: Request, model_id: UUID, staff: StaffDep, session: StaffSession
) -> StreamingResponse:
    row = await _get(session, model_id)
    if row.status != "ready":
        raise ApiError(
            "ml_model_not_found",
            "this model's file was replaced or revoked; download the current version instead",
        )
    storage = get_storage()
    try:
        present = await storage.exists(row.artifact_key)
    except Exception as error:  # noqa: BLE001
        raise ApiError(
            "release_file_unavailable",
            "the model file is temporarily unavailable; try again in a few minutes",
        ) from error
    if not present:
        raise ApiError(
            "release_file_unavailable",
            "the model file is missing from storage; publish this version again",
        )
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="ml_model.download",
        payload={"model_id": str(row.id), "kind": row.kind, "version": row.version},
        ip=client_ip(request),
    )
    ml_model_events_total.labels(action="download", result="ok").inc()
    headers = _download_headers(row)
    size = row.size_bytes
    range_header = request.headers.get("range")
    if_range = request.headers.get("if-range")
    window = None
    if range_header and (if_range is None or if_range.strip('"') == row.sha256):
        window = http_ranges.parse_range(range_header, size)
        if window is None:
            return Response(  # type: ignore[return-value]
                status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"}
            )
    if window is None:
        return StreamingResponse(
            storage.iter_chunks(row.artifact_key),
            media_type=ml_models.ONNX_MIME,
            headers={**headers, "Content-Length": str(size)},
        )
    first, last = window
    return StreamingResponse(
        storage.iter_chunks(row.artifact_key, byte_range=(first, last)),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=ml_models.ONNX_MIME,
        headers={
            **headers,
            "Content-Length": str(last - first + 1),
            "Content-Range": f"bytes {first}-{last}/{size}",
        },
    )


async def _audit_action(
    session: AsyncSession,
    staff: Principal,
    request: Request,
    action: str,
    row: MlModelRelease,
    **extra: object,
) -> None:
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action=f"ml_model.{action}",
        payload={"model_id": str(row.id), "kind": row.kind, "version": row.version, **extra},
        ip=client_ip(request),
    )
    ml_model_events_total.labels(action=action, result="ok").inc()


@router.post("/v1/admin/ml/models/{model_id}/promote", response_model=MlModelOut)
async def admin_promote_model(
    model_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: MlAdminDep,
    session: StaffSession,
) -> MlModelOut:
    """Make a `latest` model the `champion`; the earlier champion follows the retention rule."""
    await _verify_sensitive(session, staff, payload)
    row = await _get(session, model_id)
    await _kind_lock(session, row.kind)
    row = await _get(session, model_id, lock=True)
    if row.status != "ready":
        raise ApiError("ml_model_invalid", "only a ready model can be promoted")
    if row.channel == "champion":
        return MlModelOut.model_validate(row)
    now = datetime.now(UTC)
    previous = await _previous(session, kind=row.kind, channel="champion", exclude=row.id)
    row.channel, row.promoted_at = "champion", now
    doomed = retire_previous(previous, channel="champion", now=now)
    await _audit_action(
        session, staff, request, "promote", row, replaced=[str(old.id) for old in previous]
    )
    await session.flush()
    await session.refresh(row)
    out = MlModelOut.model_validate(row)
    await session.commit()
    await ml_models.delete_keys(doomed)
    return out


@router.post("/v1/admin/ml/models/{model_id}/rollout", response_model=MlModelOut)
async def admin_set_rollout(
    model_id: UUID,
    payload: MlModelRolloutRequest,
    request: Request,
    staff: MlAdminDep,
    session: StaffSession,
) -> MlModelOut:
    await _verify_sensitive(session, staff, payload)
    row = await _get(session, model_id, lock=True)
    if row.status != "ready":
        raise ApiError("ml_model_invalid", "the rollout of a model that is not ready cannot change")
    previous = row.rollout_percent
    row.rollout_percent = payload.rollout_percent
    await _audit_action(
        session,
        staff,
        request,
        "rollout",
        row,
        from_percent=previous,
        to_percent=payload.rollout_percent,
    )
    await session.flush()
    await session.refresh(row)
    return MlModelOut.model_validate(row)


@router.post("/v1/admin/ml/models/{model_id}/pin", response_model=MlModelOut)
async def admin_pin_model(
    model_id: UUID,
    payload: MlModelPinRequest,
    request: Request,
    staff: MlAdminDep,
    session: StaffSession,
) -> MlModelOut:
    await _verify_sensitive(session, staff, payload)
    row = await _get(session, model_id, lock=True)
    if row.status != "ready":
        raise ApiError("ml_model_invalid", "only a ready model can be pinned")
    row.pinned = payload.pinned
    await _audit_action(session, staff, request, "pin" if payload.pinned else "unpin", row)
    await session.flush()
    await session.refresh(row)
    return MlModelOut.model_validate(row)


@router.post("/v1/admin/ml/models/{model_id}/revoke", response_model=MlModelOut)
async def admin_revoke_model(
    model_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: MlAdminDep,
    session: StaffSession,
) -> MlModelOut:
    """Stop offering the model and delete its file; the row stays as metadata."""
    await _verify_sensitive(session, staff, payload)
    row = await _get(session, model_id, lock=True)
    if row.status != "ready":
        raise ApiError("ml_model_invalid", "only a ready model can be revoked")
    now = datetime.now(UTC)
    row.status, row.revoked_at, row.rollout_percent = "revoked", now, 0
    key = row.artifact_key
    await _audit_action(session, staff, request, "revoke", row)
    await session.flush()
    await session.refresh(row)
    out = MlModelOut.model_validate(row)
    await session.commit()
    await ml_models.delete_keys([key])
    return out


@router.post("/v1/admin/ml/models/{model_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_model(
    model_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: MlAdminDep,
    session: StaffSession,
) -> None:
    """Remove the row of a model that is no longer offered (revoked, replaced or stuck)."""
    await _verify_sensitive(session, staff, payload)
    row = await _get(session, model_id, lock=True)
    if row.status == "ready":
        raise ApiError("ml_model_invalid", "revoke this model before deleting it")
    key = row.artifact_key
    await _audit_action(session, staff, request, "delete", row)
    await session.delete(row)
    await session.commit()
    await ml_models.delete_keys([key])
