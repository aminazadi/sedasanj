"""Chunk intake for meetings: validate, bill by block, store, record and queue transcription."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import ApiError
from app.metrics import meeting_chunks_total
from app.models import AudioObject, Meeting, MeetingChunk, MeetingSegment, Tenant
from app.schemas import MeetingTranscriptIn
from app.services import billing
from app.services.audio import probe_wav_file
from app.services.queue import JOB_MEETING_CHUNK, QUEUE_MEETING, get_queue
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

MAX_DEVICE_TEXT_ITEMS = 200
MAX_DEVICE_TEXT_CHARS = 2000
# A chunk is up to `meeting_chunk_seconds_max` long, so a handful of blocks is always enough.
MAX_BLOCKS_PER_CHUNK = 4


@dataclass(frozen=True)
class ChunkUpload:
    """A chunk already spooled to disk, with the metadata the app declared for it."""

    path: Path
    declared_sha256: str
    t_start_ms: int
    t_end_ms: int
    device_text: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ChunkAccepted:
    chunk_id: UUID
    seq: int
    status: str
    duplicate: bool


def chunk_object_key(tenant_id: UUID, meeting_id: UUID, seq: int) -> str:
    return f"{tenant_id}/meetings/{meeting_id}/{seq}.wav"


def chunk_job_id(chunk_id: UUID) -> str:
    """Stable ARQ job id: a re-enqueue of the same chunk is deduplicated by the queue."""
    return f"meeting-chunk:{chunk_id}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def clean_device_text(items: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Keep only the documented draft fields, bounded in count and length."""
    if not items:
        return None
    cleaned: list[dict[str, Any]] = []
    for item in items[:MAX_DEVICE_TEXT_ITEMS]:
        try:
            cleaned.append(
                {
                    "t_start_ms": int(item["t_start_ms"]),
                    "t_end_ms": int(item["t_end_ms"]),
                    "text": str(item["text"])[:MAX_DEVICE_TEXT_CHARS],
                }
            )
        except (KeyError, TypeError, ValueError):
            raise ApiError(
                "invalid_request",
                "device_text باید فهرستی از t_start_ms، t_end_ms و text باشد؛ آن را اصلاح کنید",
            ) from None
    return cleaned


async def _ensure_block(
    session: AsyncSession, *, meeting: Meeting, tenant: Tenant, needed_seconds: int
) -> None:
    """Reserve credit blocks until the reservation covers `needed_seconds` of recorded audio."""
    settings = get_settings()
    for _ in range(MAX_BLOCKS_PER_CHUNK):
        if meeting.reserved_seconds >= needed_seconds:
            return
        balance = await billing.get_balance(session, tenant.id)
        amount = min(settings.meeting_reserve_block_seconds, balance.seconds)
        if amount <= 0:
            raise ApiError(
                "insufficient_credit",
                "اعتبار سازمان تمام شده است؛ حساب را شارژ کنید. تکه‌های قبلی پردازش می‌شوند",
            )
        reservation = await billing.reserve(
            session,
            tenant=tenant,
            meeting_id=meeting.id,
            block=meeting.reserved_blocks,
            duration_ms=amount * 1000,
        )
        meeting.reserved_seconds += reservation.seconds
        meeting.reserved_blocks += 1
    if meeting.reserved_seconds < needed_seconds:
        raise ApiError("insufficient_credit", "اعتبار سازمان کافی نیست؛ حساب را شارژ کنید")


async def _existing_chunk(session: AsyncSession, meeting_id: UUID, seq: int) -> MeetingChunk | None:
    return (
        await session.execute(
            select(MeetingChunk).where(
                MeetingChunk.meeting_id == meeting_id, MeetingChunk.seq == seq
            )
        )
    ).scalar_one_or_none()


def _replay(existing: MeetingChunk, actual_sha256: str) -> ChunkAccepted:
    if existing.sha256 != actual_sha256:
        meeting_chunks_total.labels(result="conflict").inc()
        raise ApiError(
            "meeting_chunk_conflict",
            "برای این شماره قبلاً تکه‌ای با محتوای دیگر ثبت شده؛ وضعیت جلسه را بخوانید و ادامه دهید",
        )
    meeting_chunks_total.labels(result="duplicate").inc()
    return ChunkAccepted(
        chunk_id=existing.id, seq=existing.seq, status=existing.status, duplicate=True
    )


async def accept_chunk(
    session: AsyncSession, meeting: Meeting, seq: int, upload: ChunkUpload
) -> ChunkAccepted:
    """Store one chunk idempotently by (meeting, seq).

    The caller holds the meeting row locked, so counters and billing blocks cannot race. Raises
    before anything is written when the audio or the credit is not acceptable.
    """
    if meeting.status != "receiving":
        raise ApiError("meeting_closed", "این جلسه بسته شده است؛ جلسه‌ی جدید شروع کنید")
    if upload.t_end_ms < upload.t_start_ms:
        raise ApiError("invalid_request", "t_end_ms باید بعد از t_start_ms باشد")

    actual_sha256 = await asyncio.to_thread(_file_sha256, upload.path)
    if actual_sha256 != upload.declared_sha256.strip().lower():
        meeting_chunks_total.labels(result="invalid").inc()
        raise ApiError(
            "meeting_chunk_invalid_audio",
            "هش ارسال‌شده با محتوای صدا نمی‌خواند؛ تکه را دوباره از روی فایل محلی بفرستید",
        )

    existing = await _existing_chunk(session, meeting.id, seq)
    if existing is not None:
        return _replay(existing, actual_sha256)

    try:
        probe = await probe_wav_file(upload.path)
    except ApiError as exc:
        meeting_chunks_total.labels(result="invalid").inc()
        raise ApiError(
            "meeting_chunk_invalid_audio", "فایل WAV تک‌کاناله ۱۶ کیلوهرتز بفرستید"
        ) from exc
    if probe.codec != "pcm_s16le" or probe.sample_rate != 16000 or probe.channels != 1:
        meeting_chunks_total.labels(result="invalid").inc()
        raise ApiError(
            "meeting_chunk_invalid_audio",
            "صدا باید WAV، PCM 16 بیتی، تک‌کاناله و ۱۶ کیلوهرتز باشد؛ دوباره ضبط یا تبدیل کنید",
        )

    tenant = await session.get(Tenant, meeting.tenant_id)
    if tenant is None:
        raise ApiError("unauthorized", "tenant not found")
    needed_seconds = math.ceil((meeting.received_ms + probe.duration_ms) / 1000)
    await _ensure_block(session, meeting=meeting, tenant=tenant, needed_seconds=needed_seconds)

    key = chunk_object_key(meeting.tenant_id, meeting.id, seq)
    await get_storage().put_path(key, upload.path)
    audio = AudioObject(
        tenant_id=meeting.tenant_id,
        bucket=get_storage().bucket,
        object_key=key,
        sha256=actual_sha256,
        bytes=probe.bytes,
        sample_rate=probe.sample_rate,
        channels=probe.channels,
        duration_ms=probe.duration_ms,
        expires_at=datetime.now(UTC) + timedelta(days=tenant.audio_retention_days),
    )
    session.add(audio)
    await session.flush()

    inserted = (
        await session.execute(
            pg_insert(MeetingChunk)
            .values(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                seq=seq,
                t_start_ms=upload.t_start_ms,
                t_end_ms=upload.t_end_ms,
                audio_id=audio.id,
                sha256=actual_sha256,
                bytes=probe.bytes,
                duration_ms=probe.duration_ms,
                device_text=clean_device_text(upload.device_text),
                status="received",
            )
            .on_conflict_do_nothing(index_elements=["meeting_id", "seq"])
            .returning(MeetingChunk.id)
        )
    ).scalar_one_or_none()
    if inserted is None:
        # Lost a race with a concurrent request for the same seq: compare against the winner.
        winner = await _existing_chunk(session, meeting.id, seq)
        if winner is None:
            raise ApiError("internal", "chunk insert conflicted; retry", retryable=True)
        return _replay(winner, actual_sha256)

    meeting.received_chunks += 1
    meeting.received_ms += probe.duration_ms
    meeting.updated_at = datetime.now(UTC)
    meeting_chunks_total.labels(result="accepted").inc()
    return ChunkAccepted(chunk_id=inserted, seq=seq, status="received", duplicate=False)


async def enqueue_chunk(tenant_id: UUID, meeting_id: UUID, chunk_id: UUID) -> bool:
    """Queue transcription after the commit. A failure is not an error: the reconciler requeues."""
    try:
        await get_queue().enqueue(
            QUEUE_MEETING,
            JOB_MEETING_CHUNK,
            {
                "tenant_id": str(tenant_id),
                "meeting_id": str(meeting_id),
                "chunk_id": str(chunk_id),
            },
            job_id=chunk_job_id(chunk_id),
        )
    except Exception:
        logger.warning(
            "meeting chunk enqueue failed; the reconciler will retry",
            extra={"extra_fields": {"meeting_id": str(meeting_id), "chunk_id": str(chunk_id)}},
            exc_info=True,
        )
        return False
    return True


async def mark_queued(session: AsyncSession, chunk_id: UUID) -> None:
    await session.execute(
        update(MeetingChunk)
        .where(MeetingChunk.id == chunk_id, MeetingChunk.status == "received")
        .values(status="queued", updated_at=datetime.now(UTC))
    )


async def received_seqs(session: AsyncSession, meeting_id: UUID) -> list[int]:
    rows = await session.execute(
        select(MeetingChunk.seq)
        .where(MeetingChunk.meeting_id == meeting_id)
        .order_by(MeetingChunk.seq)
    )
    return [int(seq) for seq in rows.scalars()]


async def processed_seqs(session: AsyncSession, meeting_id: UUID) -> list[int]:
    rows = await session.execute(
        select(MeetingChunk.seq)
        .where(MeetingChunk.meeting_id == meeting_id, MeetingChunk.status == "transcribed")
        .order_by(MeetingChunk.seq)
    )
    return [int(seq) for seq in rows.scalars()]


async def settle_meeting(session: AsyncSession, meeting: Meeting) -> int:
    """Charge the recorded length (the sum of chunk durations) and free the unused hold."""
    billed = await billing.settle(
        session,
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        actual_duration_ms=meeting.received_ms,
    )
    meeting.billed_seconds = billed
    return billed


async def release_meeting(session: AsyncSession, meeting: Meeting) -> None:
    await billing.release(session, tenant_id=meeting.tenant_id, meeting_id=meeting.id)


@dataclass(frozen=True)
class TranscriptAccepted:
    segments: int
    sha256: str
    replay: bool


def transcript_digest(payload: MeetingTranscriptIn) -> str:
    """Stable hash of the segment list; the app may re-send the same text any number of times."""
    canonical = json.dumps(
        [segment.model_dump() for segment in payload.segments],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_transcript(payload: MeetingTranscriptIn) -> None:
    """Order and size rules that a plain schema cannot express."""
    total_chars = 0
    previous_start = 0
    for segment in payload.segments:
        if segment.t_end_ms < segment.t_start_ms or segment.t_start_ms < previous_start:
            raise ApiError(
                "meeting_transcript_invalid",
                "زمان بخش‌های متن باید صعودی باشد؛ اپ را به‌روز کنید و متن را دوباره بفرستید",
            )
        previous_start = segment.t_start_ms
        total_chars += len(segment.text)
    if total_chars > get_settings().meeting_transcript_max_chars:
        raise ApiError(
            "meeting_transcript_invalid",
            "متن جلسه از سقف مجاز بزرگ‌تر است؛ جلسه‌های طولانی را در چند جلسه ضبط کنید",
        )


async def accept_transcript(
    session: AsyncSession, meeting: Meeting, payload: MeetingTranscriptIn
) -> TranscriptAccepted:
    """Store the on-device transcript of a text meeting, replacing any earlier upload.

    The caller holds the meeting row locked. The same text again is a replay, different text
    before `finish` replaces the previous upload.
    """
    if meeting.input_kind != "text":
        raise ApiError(
            "meeting_transcript_invalid",
            "این جلسه برای ارسال صدا شروع شده؛ در اپ جلسه‌ی جدید شروع کنید",
        )
    if meeting.status != "receiving":
        raise ApiError("meeting_closed", "این جلسه بسته شده است؛ جلسه‌ی جدید شروع کنید")
    validate_transcript(payload)
    digest = transcript_digest(payload)
    if meeting.transcript_sha256 == digest:
        return TranscriptAccepted(segments=len(payload.segments), sha256=digest, replay=True)
    await session.execute(
        delete(MeetingSegment).where(
            MeetingSegment.meeting_id == meeting.id, MeetingSegment.source == "device_asr"
        )
    )
    session.add_all(
        MeetingSegment(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            t_start_ms=segment.t_start_ms,
            t_end_ms=segment.t_end_ms,
            speaker_idx=segment.speaker,
            source="device_asr",
            text=segment.text.strip(),
        )
        for segment in payload.segments
        if segment.text.strip()
    )
    now = datetime.now(UTC)
    meeting.transcript_sha256 = digest
    meeting.transcript_received_at = now
    meeting.asr_identity = payload.asr_identity
    meeting.updated_at = now
    await session.flush()
    return TranscriptAccepted(segments=len(payload.segments), sha256=digest, replay=False)


async def transcript_end_ms(session: AsyncSession, meeting_id: UUID) -> int | None:
    return (
        await session.execute(
            select(func.max(MeetingSegment.t_end_ms)).where(MeetingSegment.meeting_id == meeting_id)
        )
    ).scalar_one_or_none()


def clamp_text_duration(requested_ms: int, transcript_end: int) -> int:
    """Billable length of a text meeting: what the app says, bounded by the text and a cap."""
    return min(max(requested_ms, transcript_end), get_settings().meeting_max_duration_ms)


async def prepare_text_finish(session: AsyncSession, meeting: Meeting, requested_ms: int) -> None:
    """Check the text is there and hold enough credit for the whole meeting before processing."""
    end_ms = await transcript_end_ms(session, meeting.id)
    if meeting.transcript_sha256 is None or end_ms is None:
        raise ApiError(
            "meeting_transcript_missing",
            "متن جلسه هنوز نرسیده است؛ در اپ «ارسال متن این جلسه» را بزنید",
        )
    duration_ms = clamp_text_duration(requested_ms, int(end_ms))
    tenant = await session.get(Tenant, meeting.tenant_id)
    if tenant is None:
        raise ApiError("unauthorized", "tenant not found")
    await _ensure_block(
        session, meeting=meeting, tenant=tenant, needed_seconds=math.ceil(duration_ms / 1000)
    )
    meeting.duration_ms = duration_ms
    meeting.received_ms = duration_ms
