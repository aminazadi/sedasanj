"""Meetings: app pairing, chunked upload from Jalase-Negar and the panel's meeting views."""

from __future__ import annotations

import json
import logging
import math
import re
import secrets
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from fastapi import Path as PathParam
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import session_scope
from app.deps import (
    ApiKeySession,
    ControlSession,
    MeetingActorDep,
    MeetingsKeyDep,
    OperatorDep,
    PublicSession,
    TenantSession,
    UserDep,
    client_ip,
)
from app.errors import ApiError
from app.models import (
    ApiKey,
    AudioObject,
    Meeting,
    MeetingChunk,
    MeetingEvent,
    MeetingMinutes,
    MeetingPairingCode,
    MeetingSegment,
    MeetingSpeaker,
    Tenant,
    User,
)
from app.schemas import (
    MeetingChunkOut,
    MeetingConfigValidation,
    MeetingDetail,
    MeetingDeviceOut,
    MeetingEventOut,
    MeetingFinishIn,
    MeetingFinishOut,
    MeetingLimits,
    MeetingListItem,
    MeetingMinutesOut,
    MeetingPage,
    MeetingPairedTenant,
    MeetingPairedUser,
    MeetingPairIn,
    MeetingPairingCodeCreate,
    MeetingPairingCodeOut,
    MeetingPairOut,
    MeetingPatch,
    MeetingSegmentOut,
    MeetingSessionIn,
    MeetingSessionOut,
    MeetingSpeakerOut,
    MeetingStatusOut,
)
from app.security import generate_api_key, hash_api_key
from app.services import (
    audit,
    billing,
    entitlements,
    meeting_ingest,
    meeting_progress,
    ratelimit,
)
from app.services.api_scopes import MOBILE_KEY_SCOPES
from app.services.ingest import ensure_monthly_plan_credit
from app.services.meeting_scope import (
    apply_meeting_scope,
    sees_all,
)
from app.services.queue import JOB_MEETING_CHUNK, JOB_MEETING_MINUTES, QUEUE_MEETING, get_queue
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/meetings", tags=["meetings"])

PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_CODE_LENGTH = 8
UPLOAD_READ_BYTES = 1024 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _limits() -> MeetingLimits:
    settings = get_settings()
    return MeetingLimits(
        chunk_max_bytes=settings.meeting_chunk_max_bytes,
        chunk_seconds_target=settings.meeting_chunk_seconds_target,
        chunk_seconds_max=settings.meeting_chunk_seconds_max,
    )


def _normalize_pairing_code(raw: str) -> str:
    return re.sub(r"[\s-]+", "", raw).upper()


def _not_found() -> ApiError:
    return ApiError("meeting_not_found", "جلسه پیدا نشد؛ فهرست جلسه‌ها را تازه کنید")


async def _tenant_active_check(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError("unauthorized", "tenant not found")
    if tenant.status != "active":
        raise ApiError("tenant_suspended", f"tenant is {tenant.status}")
    return tenant


# --------------------------------------------------------------------------- pairing and devices


@router.post(
    "/devices/pairing-codes",
    response_model=MeetingPairingCodeOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_pairing_code(
    payload: MeetingPairingCodeCreate,
    request: Request,
    session: ControlSession,
    principal: UserDep,
) -> MeetingPairingCodeOut:
    """One-time code (shown in the QR/config file) that the app swaps for its own token."""
    assert principal.tenant_id is not None
    await ratelimit.enforce(f"meeting-pairing-code:{principal.id}", 10)
    settings = get_settings()
    code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.meeting_pairing_ttl_minutes)
    session.add(
        MeetingPairingCode(
            tenant_id=principal.tenant_id,
            user_id=principal.id,
            code_hash=hash_api_key(code),
            label=(payload.label or "").strip() or None,
            expires_at=expires_at,
        )
    )
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="meeting.pairing_code.create",
        payload={"expires_at": expires_at.isoformat()},
        ip=client_ip(request),
    )
    return MeetingPairingCodeOut(
        pairing_code=code, expires_at=expires_at, server_url=settings.public_base_url
    )


@router.post("/devices/pair", response_model=MeetingPairOut, status_code=status.HTTP_201_CREATED)
async def pair_device(
    payload: MeetingPairIn, request: Request, session: PublicSession
) -> MeetingPairOut:
    """Swap a pairing code for a personal token; the token is returned exactly once."""
    settings = get_settings()
    ip = client_ip(request)
    await ratelimit.enforce(
        f"meeting-pair:{ip or 'unknown'}", settings.rate_limit_meeting_pairing_per_minute
    )
    invalid = ApiError(
        "meeting_pairing_invalid", "کد جفت‌سازی نامعتبر یا منقضی است؛ در پنل کد جدید بسازید"
    )
    now = datetime.now(UTC)
    code = (
        await session.execute(
            select(MeetingPairingCode)
            .where(
                MeetingPairingCode.code_hash
                == hash_api_key(_normalize_pairing_code(payload.pairing_code))
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if code is None or code.used_at is not None or code.expires_at <= now:
        raise invalid
    user = await session.get(User, code.user_id)
    if user is None or user.tenant_id != code.tenant_id:
        raise invalid
    tenant = await _tenant_active_check(session, code.tenant_id)

    active = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ApiKey)
                .where(
                    ApiKey.user_id == user.id,
                    ApiKey.kind == "mobile",
                    ApiKey.revoked_at.is_(None),
                )
            )
        ).scalar_one()
    )
    if active >= settings.meeting_token_limit:
        raise ApiError(
            "meeting_token_limit",
            f"حداکثر {settings.meeting_token_limit} دستگاه فعال مجاز است؛ یک دستگاه را ابطال کنید",
        )

    secret, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        tenant_id=code.tenant_id,
        user_id=user.id,
        kind="mobile",
        key_hash=key_hash,
        key_prefix=prefix,
        label=payload.device_label.strip(),
        archive_format="gzip",
        scopes=list(MOBILE_KEY_SCOPES),
    )
    session.add(api_key)
    code.used_at = now
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=user.id,
        tenant_id=code.tenant_id,
        action="meeting.device.pair",
        payload={
            "api_key_id": str(api_key.id),
            "platform": payload.platform,
            "app_version": payload.app_version,
        },
        ip=ip,
    )
    return MeetingPairOut(
        token=secret,
        token_prefix=prefix,
        user=MeetingPairedUser(display_name=user.display_name),
        tenant=MeetingPairedTenant(name=tenant.name),
        limits=_limits(),
    )


@router.get("/devices")
async def list_devices(
    session: ControlSession, principal: UserDep
) -> dict[str, list[MeetingDeviceOut]]:
    rows = (
        (
            await session.execute(
                select(ApiKey)
                .where(
                    ApiKey.user_id == principal.id,
                    ApiKey.kind == "mobile",
                    ApiKey.tenant_id == principal.tenant_id,
                )
                .order_by(ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            MeetingDeviceOut(
                id=row.id,
                label=row.label,
                token_prefix=row.key_prefix,
                last_used_at=row.last_used_at,
                created_at=row.created_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]
    }


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: UUID, request: Request, session: ControlSession, principal: UserDep
) -> None:
    revoked = await session.execute(
        update(ApiKey)
        .where(
            ApiKey.id == device_id,
            ApiKey.user_id == principal.id,
            ApiKey.kind == "mobile",
            ApiKey.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
        .returning(ApiKey.id)
    )
    if revoked.scalar_one_or_none() is None:
        raise ApiError("not_found", "دستگاه پیدا نشد؛ فهرست دستگاه‌ها را تازه کنید")
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="meeting.device.revoke",
        payload={"api_key_id": str(device_id)},
        ip=client_ip(request),
    )


@router.get("/config/validate", response_model=MeetingConfigValidation)
async def validate_config(principal: MeetingsKeyDep) -> MeetingConfigValidation:
    """Connection test for the app; also lets it compare its clock with the server."""
    assert principal.tenant_id is not None and principal.user_id is not None
    async with session_scope(None, staff=True) as session:
        user = await session.get(User, principal.user_id)
        tenant = await session.get(Tenant, principal.tenant_id)
    if user is None or tenant is None:
        raise ApiError("unauthorized", "user no longer exists")
    return MeetingConfigValidation(
        ok=True,
        user=MeetingPairedUser(display_name=user.display_name),
        tenant=MeetingPairedTenant(name=tenant.name),
        limits=_limits(),
        server_time=datetime.now(UTC),
    )


# --------------------------------------------------------------------------- app: session cycle


async def _owned_meeting(
    session: AsyncSession,
    meeting_id: UUID,
    principal_user_id: UUID,
    tenant_id: UUID,
    *,
    lock: bool = False,
) -> Meeting:
    stmt = select(Meeting).where(
        Meeting.id == meeting_id,
        Meeting.tenant_id == tenant_id,
        Meeting.owner_user_id == principal_user_id,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    meeting = (await session.execute(stmt)).scalar_one_or_none()
    if meeting is None:
        raise _not_found()
    return meeting


@router.post("/sessions", response_model=MeetingSessionOut)
async def create_session(
    payload: MeetingSessionIn,
    response: Response,
    principal: MeetingsKeyDep,
    session: ApiKeySession,
) -> MeetingSessionOut:
    """Start (or resume) a meeting; idempotent on the app's own `client_meeting_id`."""
    assert principal.tenant_id is not None and principal.user_id is not None
    tenant_id, user_id = principal.tenant_id, principal.user_id
    settings = get_settings()

    existing = (
        await session.execute(
            select(Meeting).where(
                Meeting.tenant_id == tenant_id,
                Meeting.client_meeting_id == payload.client_meeting_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.owner_user_id != user_id:
            raise _not_found()
        return MeetingSessionOut(
            meeting_id=existing.id,
            status=existing.status,
            received_seqs=await meeting_ingest.received_seqs(session, existing.id),
            chunk_max_bytes=settings.meeting_chunk_max_bytes,
        )

    tenant = await _tenant_active_check(session, tenant_id)
    plan_price = await ensure_monthly_plan_credit(session, tenant_id, datetime.now(UTC))
    entitlement = await entitlements.effective(session, tenant_id)
    entitlement = await entitlements.require_upload_consumption(
        session,
        tenant_id,
        price_per_minute_toman=plan_price if plan_price > 0 else entitlement.price_per_minute_toman,
    )
    balance = await billing.get_balance(session, tenant_id)
    if balance.seconds < settings.meeting_min_balance_seconds:
        raise ApiError(
            "insufficient_credit",
            f"برای شروع جلسه حداقل {settings.meeting_min_balance_seconds // 60} دقیقه اعتبار "
            "لازم است؛ حساب را شارژ کنید",
        )

    meeting = Meeting(
        tenant_id=tenant_id,
        owner_user_id=user_id,
        client_meeting_id=payload.client_meeting_id,
        title=(payload.title or "").strip() or None,
        status="receiving",
        started_at=payload.started_at,
        sample_rate=payload.sample_rate,
        channels=payload.channels,
        app_version=payload.app_version,
    )
    try:
        async with session.begin_nested():
            session.add(meeting)
            await session.flush()
    except IntegrityError:
        # Two requests raced on the same client_meeting_id: hand back the winner.
        winner = (
            await session.execute(
                select(Meeting).where(
                    Meeting.tenant_id == tenant_id,
                    Meeting.client_meeting_id == payload.client_meeting_id,
                )
            )
        ).scalar_one_or_none()
        if winner is None or winner.owner_user_id != user_id:
            raise _not_found() from None
        return MeetingSessionOut(
            meeting_id=winner.id,
            status=winner.status,
            received_seqs=await meeting_ingest.received_seqs(session, winner.id),
            chunk_max_bytes=settings.meeting_chunk_max_bytes,
        )

    block = min(settings.meeting_reserve_block_seconds, balance.seconds)
    reservation = await billing.reserve(
        session,
        tenant=tenant,
        meeting_id=meeting.id,
        block=0,
        duration_ms=block * 1000,
        price_per_minute_toman=entitlement.price_per_minute_toman,
    )
    meeting.reserved_seconds = reservation.seconds
    meeting.reserved_blocks = 1
    meeting_progress.set_stage(meeting, "receiving", progress_pct=0)
    await meeting_progress.record_event(
        session,
        meeting,
        step_key="receiving",
        kind="pipeline",
        status="receiving",
        detail=meeting_progress.STAGE_LABELS["receiving"],
    )
    response.status_code = status.HTTP_201_CREATED
    return MeetingSessionOut(
        meeting_id=meeting.id,
        status=meeting.status,
        received_seqs=[],
        chunk_max_bytes=settings.meeting_chunk_max_bytes,
    )


async def _spool_upload(upload: UploadFile, target: Path, max_bytes: int) -> int:
    size = 0
    with target.open("wb") as handle:
        while block := await upload.read(UPLOAD_READ_BYTES):
            size += len(block)
            if size > max_bytes:
                raise ApiError(
                    "meeting_chunk_too_large",
                    f"تکه از سقف {max_bytes // (1024 * 1024)} مگابایت بزرگ‌تر است؛ "
                    "تکه‌ها را کوتاه‌تر کنید",
                )
            handle.write(block)
    return size


@router.put("/{meeting_id}/chunks/{seq}", response_model=MeetingChunkOut)
async def put_chunk(
    meeting_id: UUID,
    seq: Annotated[int, PathParam(ge=0, le=100000)],
    principal: MeetingsKeyDep,
    audio: Annotated[UploadFile, File()],
    t_start_ms: Annotated[int, Form(ge=0)],
    t_end_ms: Annotated[int, Form(ge=0)],
    sha256: Annotated[str, Form(min_length=64, max_length=64, pattern="^[0-9a-fA-F]{64}$")],
    device_text: Annotated[str | None, Form(max_length=200_000)] = None,
) -> MeetingChunkOut:
    """Idempotent on (meeting, seq): the same hash replays, a different hash is a conflict."""
    assert principal.tenant_id is not None and principal.user_id is not None
    settings = get_settings()
    parsed_text: list[dict[str, Any]] | None = None
    if device_text:
        try:
            decoded = json.loads(device_text)
        except json.JSONDecodeError:
            raise ApiError("invalid_request", "device_text باید JSON معتبر باشد") from None
        if not isinstance(decoded, list):
            raise ApiError("invalid_request", "device_text باید فهرست باشد")
        parsed_text = cast("list[dict[str, Any]]", decoded)

    with tempfile.TemporaryDirectory(prefix="meeting-chunk-") as tmp:
        path = Path(tmp) / f"{seq}.wav"
        size = await _spool_upload(audio, path, settings.meeting_chunk_max_bytes)
        if size == 0:
            raise ApiError(
                "meeting_chunk_invalid_audio", "فایل صدا خالی است؛ تکه را دوباره بفرستید"
            )
        accepted: meeting_ingest.ChunkAccepted | None = None
        async with session_scope(principal.tenant_id) as session:
            meeting = await _owned_meeting(
                session, meeting_id, principal.user_id, principal.tenant_id, lock=True
            )
            accepted = await meeting_ingest.accept_chunk(
                session,
                meeting,
                seq,
                meeting_ingest.ChunkUpload(
                    path=path,
                    declared_sha256=sha256,
                    t_start_ms=t_start_ms,
                    t_end_ms=t_end_ms,
                    device_text=parsed_text,
                ),
            )

    assert accepted is not None
    # Queue after the commit so a worker never sees a chunk that is not yet visible. A failed
    # enqueue is harmless: the chunk stays `received` and the reconciler picks it up.
    if accepted.status == "received" and await meeting_ingest.enqueue_chunk(
        principal.tenant_id, meeting_id, accepted.chunk_id
    ):
        async with session_scope(principal.tenant_id) as session:
            await meeting_ingest.mark_queued(session, accepted.chunk_id)
    return MeetingChunkOut(seq=accepted.seq, status=accepted.status)


@router.get("/{meeting_id}/status", response_model=MeetingStatusOut)
async def meeting_status(meeting_id: UUID, principal: MeetingActorDep) -> MeetingStatusOut:
    assert principal.tenant_id is not None
    async with session_scope(principal.tenant_id) as session:
        meeting = (
            await session.execute(
                apply_meeting_scope(select(Meeting).where(Meeting.id == meeting_id), principal)
            )
        ).scalar_one_or_none()
        if meeting is None:
            raise _not_found()
        return MeetingStatusOut(
            status=meeting.status,
            received_seqs=await meeting_ingest.received_seqs(session, meeting.id),
            processed_seqs=await meeting_ingest.processed_seqs(session, meeting.id),
            progress_pct=meeting.progress_pct,
            progress_detail=meeting.progress_detail,
            error_code=meeting.error_code,
        )


@router.post(
    "/{meeting_id}/finish",
    response_model=MeetingFinishOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def finish_meeting(
    meeting_id: UUID, payload: MeetingFinishIn, principal: MeetingsKeyDep
) -> MeetingFinishOut:
    """Close the recording. Missing chunks keep the meeting open and are listed to the app."""
    assert principal.tenant_id is not None and principal.user_id is not None
    async with session_scope(principal.tenant_id) as session:
        meeting = await _owned_meeting(
            session, meeting_id, principal.user_id, principal.tenant_id, lock=True
        )
        if meeting.status in ("processing", "complete"):
            return MeetingFinishOut(meeting_id=meeting.id, status=meeting.status)
        if meeting.status != "receiving":
            raise ApiError("meeting_closed", "این جلسه بسته شده است؛ جلسه‌ی جدید شروع کنید")
        have = set(await meeting_ingest.received_seqs(session, meeting.id))
        missing = [seq for seq in range(payload.total_chunks) if seq not in have]
        if missing:
            raise ApiError(
                "meeting_incomplete_chunks",
                "بعضی تکه‌ها هنوز نرسیده‌اند؛ آن‌ها را دوباره بفرستید و پایان جلسه را تکرار کنید",
                extra={"missing_seqs": missing[:1000]},
            )
        now = datetime.now(UTC)
        meeting.status = "processing"
        meeting.ended_at = payload.ended_at
        meeting.finish_requested_at = now
        meeting.total_chunks = payload.total_chunks
        meeting.duration_ms = payload.duration_ms
        meeting.updated_at = now
        meeting.progress_pct = meeting_progress.compute_progress(
            total_chunks=meeting.total_chunks,
            received_chunks=meeting.received_chunks,
            processed_chunks=meeting.processed_chunks,
        )
        meeting_progress.set_stage(meeting, "processing")
        await meeting_progress.record_event(
            session,
            meeting,
            step_key="finished",
            kind="pipeline",
            status="processing",
            detail=meeting_progress.STAGE_LABELS["processing"],
        )
        return MeetingFinishOut(meeting_id=meeting.id, status=meeting.status)


@router.post("/{meeting_id}/cancel", response_model=MeetingFinishOut)
async def cancel_meeting(
    meeting_id: UUID, request: Request, principal: MeetingsKeyDep
) -> MeetingFinishOut:
    assert principal.tenant_id is not None and principal.user_id is not None
    async with session_scope(principal.tenant_id) as session:
        meeting = await _owned_meeting(
            session, meeting_id, principal.user_id, principal.tenant_id, lock=True
        )
        if meeting.status == "canceled":
            return MeetingFinishOut(meeting_id=meeting.id, status=meeting.status)
        if meeting.status == "complete":
            raise ApiError("meeting_closed", "جلسه‌ی کامل‌شده را نمی‌توان لغو کرد؛ آن را حذف کنید")
        await meeting_ingest.release_meeting(session, meeting)
        meeting.status = "canceled"
        meeting.updated_at = datetime.now(UTC)
        meeting_progress.set_stage(meeting, "canceled")
        await meeting_progress.record_event(
            session,
            meeting,
            step_key="canceled",
            kind="pipeline",
            status="canceled",
            detail=meeting_progress.STAGE_LABELS["canceled"],
        )
        await audit.record(
            session,
            actor_type="api_key",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="meeting.cancel",
            payload={"meeting_id": str(meeting.id)},
            ip=client_ip(request),
        )
        return MeetingFinishOut(meeting_id=meeting.id, status=meeting.status)


# --------------------------------------------------------------------------- panel


def _page_count(total: int, page_size: int) -> int:
    return max(1, math.ceil(total / page_size))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _list_item(meeting: Meeting, owner_name: str | None, audio_available: bool) -> dict[str, Any]:
    return {
        "id": meeting.id,
        "owner_user_id": meeting.owner_user_id,
        "owner_name": owner_name,
        "title": meeting.title,
        "status": meeting.status,
        "started_at": meeting.started_at,
        "ended_at": meeting.ended_at,
        "duration_ms": meeting.duration_ms,
        "speaker_count": meeting.speaker_count,
        "progress_pct": meeting.progress_pct,
        "progress_detail": meeting.progress_detail,
        "error_code": meeting.error_code,
        "audio_available": audio_available,
    }


@router.get("", response_model=MeetingPage)
async def list_meetings(
    session: TenantSession,
    principal: UserDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    meeting_status: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    owner_id: UUID | None = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> MeetingPage:
    stmt = apply_meeting_scope(select(Meeting), principal)
    if owner_id is not None:
        if not sees_all(principal) and owner_id != principal.id:
            raise ApiError("forbidden", "فقط مدیر سازمان می‌تواند جلسه‌های دیگران را فیلتر کند")
        stmt = stmt.where(Meeting.owner_user_id == owner_id)
    if q and q.strip():
        stmt = stmt.where(Meeting.title.ilike(f"%{_escape_like(q.strip())}%", escape="\\"))
    if meeting_status:
        stmt = stmt.where(Meeting.status == meeting_status)
    if date_from is not None:
        stmt = stmt.where(Meeting.started_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Meeting.started_at <= date_to)
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = (
        await session.execute(
            stmt.add_columns(User.display_name, User.email, AudioObject.deleted_at)
            .outerjoin(User, User.id == Meeting.owner_user_id)
            .outerjoin(AudioObject, AudioObject.id == Meeting.audio_id)
            .order_by(Meeting.started_at.desc(), Meeting.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        MeetingListItem(
            **_list_item(
                row[0],
                row[1] or row[2],
                row[0].audio_id is not None and row[3] is None,
            )
        )
        for row in rows
    ]
    return MeetingPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=_page_count(total, page_size),
    )


async def _visible_meeting(
    session: AsyncSession, meeting_id: UUID, principal: Any, *, lock: bool = False
) -> Meeting:
    stmt = apply_meeting_scope(select(Meeting).where(Meeting.id == meeting_id), principal)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    meeting = (await session.execute(stmt)).scalar_one_or_none()
    if meeting is None:
        raise _not_found()
    return meeting


async def _audio_available(session: AsyncSession, meeting: Meeting) -> bool:
    if meeting.audio_id is None:
        return False
    audio = await session.get(AudioObject, meeting.audio_id)
    return audio is not None and audio.deleted_at is None


def _minutes_out(row: MeetingMinutes) -> MeetingMinutesOut:
    return MeetingMinutesOut(
        version=row.version,
        content_md=row.content_md,
        structured=row.structured,
        model=row.model,
        is_selected=row.is_selected,
        created_at=row.created_at,
    )


@router.get("/{meeting_id}", response_model=MeetingDetail)
async def get_meeting(
    meeting_id: UUID, session: TenantSession, principal: UserDep
) -> MeetingDetail:
    meeting = await _visible_meeting(session, meeting_id, principal)
    owner = await session.get(User, meeting.owner_user_id)
    segments = (
        (
            await session.execute(
                select(MeetingSegment)
                .where(MeetingSegment.meeting_id == meeting.id)
                .order_by(MeetingSegment.t_start_ms, MeetingSegment.id)
            )
        )
        .scalars()
        .all()
    )
    speakers = (
        (
            await session.execute(
                select(MeetingSpeaker)
                .where(MeetingSpeaker.meeting_id == meeting.id)
                .order_by(MeetingSpeaker.speaker_idx)
            )
        )
        .scalars()
        .all()
    )
    selected = (
        await session.execute(
            select(MeetingMinutes)
            .where(MeetingMinutes.meeting_id == meeting.id)
            .order_by(MeetingMinutes.is_selected.desc(), MeetingMinutes.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    events = (
        (
            await session.execute(
                select(MeetingEvent)
                .where(MeetingEvent.meeting_id == meeting.id)
                .order_by(MeetingEvent.created_at, MeetingEvent.id)
            )
        )
        .scalars()
        .all()
    )
    return MeetingDetail(
        **_list_item(
            meeting,
            (owner.display_name or owner.email) if owner is not None else None,
            await _audio_available(session, meeting),
        ),
        segments=[
            MeetingSegmentOut(
                id=s.id,
                t_start_ms=s.t_start_ms,
                t_end_ms=s.t_end_ms,
                speaker_idx=s.speaker_idx,
                text=s.text,
            )
            for s in segments
        ],
        speakers=[
            MeetingSpeakerOut(
                speaker_idx=s.speaker_idx, label=s.label, user_id=s.user_id, total_ms=s.total_ms
            )
            for s in speakers
        ],
        minutes=_minutes_out(selected) if selected is not None else None,
        processing_events=[
            MeetingEventOut(
                id=e.id,
                step_key=e.step_key,
                kind=e.kind,
                status=e.status,
                detail=e.detail,
                created_at=e.created_at,
            )
            for e in events
        ],
    )


def _parse_range(header: str | None, length: int) -> tuple[int, int] | None:
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if match is None or (not match.group(1) and not match.group(2)):
        return None
    if match.group(1):
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) else length - 1
    else:
        suffix = int(match.group(2))
        first, last = max(length - suffix, 0), length - 1
    last = min(last, length - 1)
    if first > last or first >= length:
        raise ApiError("invalid_request", "Range خارج از اندازه‌ی فایل است")
    return first, last


@router.get("/{meeting_id}/audio/content")
async def get_meeting_audio(
    meeting_id: UUID, request: Request, session: TenantSession, principal: UserDep
) -> Response:
    """Whole-meeting WAV once it is assembled, with `Range` support for seeking."""
    meeting = await _visible_meeting(session, meeting_id, principal)
    audio = await session.get(AudioObject, meeting.audio_id) if meeting.audio_id else None
    if audio is None or audio.deleted_at is not None:
        raise ApiError(
            "not_found",
            "صدای کامل جلسه هنوز آماده نیست یا طبق سیاست نگهداری حذف شده است",
        )
    window = _parse_range(request.headers.get("range"), int(audio.bytes))
    if window is None or window[0] == 0:
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="meeting.audio.download",
            payload={"meeting_id": str(meeting.id)},
            ip=client_ip(request),
        )
    storage = get_storage()
    length = int(audio.bytes)

    async def stream() -> AsyncIterator[bytes]:
        async for block in storage.iter_chunks(audio.object_key, byte_range=window):
            yield block

    headers = {"Accept-Ranges": "bytes"}
    if window is None:
        headers["Content-Length"] = str(length)
        return StreamingResponse(stream(), media_type="audio/wav", headers=headers)
    first, last = window
    headers["Content-Range"] = f"bytes {first}-{last}/{length}"
    headers["Content-Length"] = str(last - first + 1)
    return StreamingResponse(
        stream(),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type="audio/wav",
        headers=headers,
    )


@router.patch("/{meeting_id}", response_model=MeetingDetail)
async def update_meeting(
    meeting_id: UUID,
    payload: MeetingPatch,
    request: Request,
    session: TenantSession,
    principal: OperatorDep,
) -> MeetingDetail:
    assert principal.tenant_id is not None
    meeting = await _visible_meeting(session, meeting_id, principal, lock=True)
    changed: list[str] = []
    if "title" in payload.model_fields_set:
        meeting.title = (payload.title or "").strip() or None
        changed.append("title")
    if payload.speakers:
        wanted = {item.speaker_idx: item for item in payload.speakers}
        rows = (
            (
                await session.execute(
                    select(MeetingSpeaker).where(
                        MeetingSpeaker.meeting_id == meeting.id,
                        MeetingSpeaker.speaker_idx.in_(list(wanted)),
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(rows) != len(wanted):
            raise ApiError(
                "invalid_request", "گوینده‌ی انتخاب‌شده در این جلسه نیست؛ جزئیات را تازه کنید"
            )
        linked = {item.user_id for item in wanted.values() if item.user_id is not None}
        if linked:
            found = set(
                (
                    await session.execute(
                        select(User.id).where(
                            User.id.in_(linked), User.tenant_id == principal.tenant_id
                        )
                    )
                ).scalars()
            )
            if found != linked:
                raise ApiError("invalid_request", "کاربر انتخاب‌شده در این سازمان نیست")
        for row in rows:
            item = wanted[row.speaker_idx]
            row.label = item.label.strip()
            row.user_id = item.user_id
        changed.append("speakers")
    if changed:
        meeting.updated_at = datetime.now(UTC)
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="meeting.update",
            payload={"meeting_id": str(meeting.id), "fields": changed},
            ip=client_ip(request),
        )
    return await get_meeting(meeting_id, session, principal)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: UUID, request: Request, session: TenantSession, principal: OperatorDep
) -> None:
    """Owner or org_admin. Held credit is returned and every stored chunk is removed."""
    assert principal.tenant_id is not None
    meeting = await _visible_meeting(session, meeting_id, principal, lock=True)
    await meeting_ingest.release_meeting(session, meeting)
    audio_ids = set(
        (
            await session.execute(
                select(MeetingChunk.audio_id).where(
                    MeetingChunk.meeting_id == meeting.id, MeetingChunk.audio_id.is_not(None)
                )
            )
        ).scalars()
    )
    if meeting.audio_id is not None:
        audio_ids.add(meeting.audio_id)
    storage = get_storage()
    now = datetime.now(UTC)
    if audio_ids:
        for audio in (
            (await session.execute(select(AudioObject).where(AudioObject.id.in_(audio_ids))))
            .scalars()
            .all()
        ):
            if audio.deleted_at is None:
                await storage.delete(audio.object_key)
                audio.deleted_at = now
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="meeting.delete",
        payload={"meeting_id": str(meeting.id), "owner_user_id": str(meeting.owner_user_id)},
        ip=client_ip(request),
    )
    await session.execute(delete(Meeting).where(Meeting.id == meeting.id))


@router.post("/{meeting_id}/reanalyze", status_code=status.HTTP_202_ACCEPTED)
async def reanalyze_meeting(
    meeting_id: UUID, request: Request, principal: OperatorDep
) -> dict[str, str]:
    """Build a new minutes version from the existing transcript; never re-billed."""
    assert principal.tenant_id is not None
    async with session_scope(principal.tenant_id) as session:
        meeting = await _visible_meeting(session, meeting_id, principal, lock=True)
        if meeting.status != "complete":
            raise ApiError(
                "meeting_closed",
                "بازتحلیل فقط برای جلسه‌ی کامل‌شده ممکن است؛ منتظر پایان پردازش بمانید",
            )
        version = int(
            (
                await session.execute(
                    select(func.coalesce(func.max(MeetingMinutes.version), 0)).where(
                        MeetingMinutes.meeting_id == meeting.id
                    )
                )
            ).scalar_one()
        )
        meeting.status = "processing"
        meeting.error_code = None
        meeting.updated_at = datetime.now(UTC)
        meeting_progress.set_stage(meeting, "minutes", progress_pct=80)
        await meeting_progress.record_event(
            session,
            meeting,
            step_key=f"reanalyze:{version + 1}",
            kind="minutes",
            status="queued",
            detail=meeting_progress.STAGE_LABELS["minutes"],
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="meeting.reanalyze",
            payload={"meeting_id": str(meeting.id)},
            ip=client_ip(request),
        )
    await _enqueue_minutes(principal.tenant_id, meeting_id, version + 1)
    return {"status": "processing"}


async def _enqueue_minutes(tenant_id: UUID, meeting_id: UUID, version: int) -> None:
    try:
        await get_queue().enqueue(
            QUEUE_MEETING,
            JOB_MEETING_MINUTES,
            {"tenant_id": str(tenant_id), "meeting_id": str(meeting_id), "version": version},
            job_id=f"meeting-minutes:{meeting_id}:{version}:{uuid4().hex[:8]}",
        )
    except Exception:
        logger.warning(
            "meeting minutes enqueue failed",
            extra={"extra_fields": {"meeting_id": str(meeting_id)}},
            exc_info=True,
        )


@router.post("/{meeting_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_meeting(
    meeting_id: UUID, request: Request, principal: OperatorDep
) -> dict[str, str]:
    """Re-run whatever failed: chunks that could not be transcribed, or the minutes."""
    assert principal.tenant_id is not None
    failed_ids: list[UUID] = []
    async with session_scope(principal.tenant_id) as session:
        meeting = await _visible_meeting(session, meeting_id, principal, lock=True)
        if meeting.status not in ("failed_retryable", "failed_terminal", "processing"):
            raise ApiError(
                "meeting_closed", "فقط جلسه‌ی ناموفق یا در حال پردازش را می‌توان دوباره امتحان کرد"
            )
        failed_ids = list(
            (
                await session.execute(
                    select(MeetingChunk.id).where(
                        MeetingChunk.meeting_id == meeting.id, MeetingChunk.status == "failed"
                    )
                )
            ).scalars()
        )
        if failed_ids:
            await session.execute(
                update(MeetingChunk)
                .where(MeetingChunk.id.in_(failed_ids))
                .values(status="received", attempts=0, error_code=None, updated_at=func.now())
            )
        meeting.status = "processing"
        meeting.error_code = None
        meeting.updated_at = datetime.now(UTC)
        meeting_progress.set_stage(meeting, "processing")
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=principal.tenant_id,
            action="meeting.retry",
            payload={"meeting_id": str(meeting.id), "chunks": len(failed_ids)},
            ip=client_ip(request),
        )
    queue = get_queue()
    for chunk_id in failed_ids:
        try:
            await queue.enqueue(
                QUEUE_MEETING,
                JOB_MEETING_CHUNK,
                {
                    "tenant_id": str(principal.tenant_id),
                    "meeting_id": str(meeting_id),
                    "chunk_id": str(chunk_id),
                },
                job_id=f"{meeting_ingest.chunk_job_id(chunk_id)}:retry:{uuid4().hex[:8]}",
            )
        except Exception:
            logger.warning(
                "meeting retry enqueue failed",
                extra={"extra_fields": {"meeting_id": str(meeting_id)}},
                exc_info=True,
            )
    if not failed_ids:
        await _enqueue_minutes(principal.tenant_id, meeting_id, 0)
    return {"status": "processing"}


@router.get("/{meeting_id}/minutes")
async def list_minutes(
    meeting_id: UUID, session: TenantSession, principal: UserDep
) -> dict[str, list[MeetingMinutesOut]]:
    meeting = await _visible_meeting(session, meeting_id, principal)
    rows = (
        (
            await session.execute(
                select(MeetingMinutes)
                .where(MeetingMinutes.meeting_id == meeting.id)
                .order_by(MeetingMinutes.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_minutes_out(row) for row in rows]}


@router.post("/{meeting_id}/minutes/{version}/select", response_model=MeetingMinutesOut)
async def select_minutes(
    meeting_id: UUID,
    version: int,
    request: Request,
    session: TenantSession,
    principal: OperatorDep,
) -> MeetingMinutesOut:
    meeting = await _visible_meeting(session, meeting_id, principal, lock=True)
    chosen = (
        await session.execute(
            select(MeetingMinutes).where(
                MeetingMinutes.meeting_id == meeting.id, MeetingMinutes.version == version
            )
        )
    ).scalar_one_or_none()
    if chosen is None:
        raise ApiError("not_found", "نسخه‌ی صورت‌جلسه پیدا نشد؛ فهرست نسخه‌ها را تازه کنید")
    await session.execute(
        update(MeetingMinutes)
        .where(MeetingMinutes.meeting_id == meeting.id)
        .values(is_selected=(MeetingMinutes.version == version))
    )
    chosen.is_selected = True
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="meeting.minutes.select",
        payload={"meeting_id": str(meeting.id), "version": version},
        ip=client_ip(request),
    )
    return _minutes_out(chosen)
