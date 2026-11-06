"""Whole-meeting WAV of a text meeting, assembled from the chunks the app uploaded.

Text meetings are never transcribed on the server: the audio is only stored so the panel can play
it. The chunks are joined into one WAV (the object the panel streams with `Range`) and the chunk
copies are then removed to halve the stored bytes.
"""

from __future__ import annotations

import hashlib
import logging
import struct
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from sqlalchemy import select

from app.db import session_scope
from app.errors import ApiError
from app.models import AudioObject, Meeting, MeetingChunk, Tenant
from app.services.audio import probe_wav_file
from app.services.audio_lifecycle import (
    has_audio_reference,
    keep_uploaded,
    protect_tenant_media,
    queue_delete,
    retire_audio,
)
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
_HEADER_BYTES = 44


def wav_data(body: bytes) -> bytes:
    """PCM payload of a RIFF/WAVE file, skipping any extra chunks before `data`."""
    if body[:4] != b"RIFF" or body[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos = 12
    while pos + 8 <= len(body):
        tag = body[pos : pos + 4]
        (size,) = struct.unpack_from("<I", body, pos + 4)
        if tag == b"data":
            # A streamed writer may leave the size at 0 or too large; trust the file length.
            end = len(body) if size == 0 or pos + 8 + size > len(body) else pos + 8 + size
            return body[pos + 8 : end]
        pos += 8 + size + (size & 1)
    raise ValueError("WAV has no data chunk")


def wav_header(data_bytes: int) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_bytes)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16)
        + b"data"
        + struct.pack("<I", data_bytes)
    )


async def assemble_meeting_audio(tenant_id: UUID, meeting_id: UUID) -> str:
    """Join the chunks without exposing partial audio or deleting a concurrent result."""
    async with protect_tenant_media(tenant_id):
        return await _assemble_meeting_audio(tenant_id, meeting_id)


def _incomplete() -> ApiError:
    return ApiError(
        "meeting_incomplete_chunks",
        "تکه‌های صدای جلسه کامل یا سالم نیستند. فایل‌های ضبط‌شده را بررسی کنید.",
    )


async def _assemble_meeting_audio(tenant_id: UUID, meeting_id: UUID) -> str:
    storage = get_storage()
    async with session_scope(tenant_id) as session:
        meeting = await session.get(Meeting, meeting_id)
        if meeting is None:
            return "missing"
        if meeting.audio_id is not None:
            return "done"
        if not meeting.total_chunks or meeting.status in {"receiving", "canceled"}:
            return "no_chunks"
        chunks = (
            await session.execute(
                select(MeetingChunk.seq, AudioObject)
                .outerjoin(AudioObject, AudioObject.id == MeetingChunk.audio_id)
                .where(
                    MeetingChunk.tenant_id == tenant_id,
                    MeetingChunk.meeting_id == meeting_id,
                    MeetingChunk.seq < meeting.total_chunks,
                )
                .order_by(MeetingChunk.seq)
            )
        ).all()
        if len(chunks) != meeting.total_chunks or any(
            seq != index or audio is None or audio.deleted_at is not None
            for index, (seq, audio) in enumerate(chunks)
        ):
            raise _incomplete()
        tenant = await session.get(Tenant, tenant_id)
        retention_days = tenant.audio_retention_days if tenant is not None else 30

    key = f"{tenant_id}/meetings/{meeting_id}/full-{uuid4().hex}.wav"
    with tempfile.TemporaryDirectory(prefix="meeting-audio-") as tmp:
        path = Path(tmp) / "full.wav"
        total = 0
        with path.open("wb") as out:
            out.write(b"\0" * _HEADER_BYTES)
            for _, source in chunks:
                try:
                    body = await storage.get(source.object_key)
                except KeyError as exc:
                    raise _incomplete() from exc
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code")
                    if code in {"404", "NoSuchKey", "NotFound"}:
                        raise _incomplete() from exc
                    raise
                if len(body) != source.bytes or hashlib.sha256(body).hexdigest() != source.sha256:
                    raise _incomplete()
                try:
                    data = wav_data(body)
                except ValueError as exc:
                    raise _incomplete() from exc
                out.write(data)
                total += len(data)
            out.seek(0)
            out.write(wav_header(total))
        probe = await probe_wav_file(path)
        # Arm cleanup before uploading. The read lock keeps the sweeper away until publication
        # commits, or until an interrupted attempt releases the lock.
        async with session_scope(tenant_id) as session:
            await queue_delete(session, tenant_id, storage.bucket, key, probe.bytes)
        await storage.put_path(key, path)
        uploaded = hashlib.sha256()
        async for block in storage.iter_chunks(key):
            uploaded.update(block)
        if uploaded.hexdigest() != probe.sha256:
            raise ApiError(
                "meeting_audio_storage_unavailable",
                "صحت فایل جلسه تأیید نشد. فضای ذخیره‌سازی را بررسی و دوباره تلاش کنید.",
            )

    async with session_scope(tenant_id) as session:
        meeting = await session.get(Meeting, meeting_id, with_for_update=True)
        if meeting is None or meeting.audio_id is not None or meeting.status == "canceled":
            return "done"
        audio = AudioObject(
            tenant_id=tenant_id,
            bucket=storage.bucket,
            object_key=key,
            sha256=probe.sha256,
            bytes=probe.bytes,
            sample_rate=probe.sample_rate,
            channels=probe.channels,
            duration_ms=probe.duration_ms,
            expires_at=datetime.now(UTC) + timedelta(days=retention_days),
        )
        session.add(audio)
        await session.flush()
        meeting.audio_id = audio.id
        await keep_uploaded(session, tenant_id, storage.bucket, key)
        # The live reference disarms cleanup for the assembled file. Original chunks are retired
        # in the same transaction and are physically removed by the storage sweeper.
        for chunk_audio in (
            (
                await session.execute(
                    select(AudioObject)
                    .join(MeetingChunk, MeetingChunk.audio_id == AudioObject.id)
                    .where(
                        MeetingChunk.meeting_id == meeting_id,
                        MeetingChunk.seq < meeting.total_chunks,
                        AudioObject.deleted_at.is_(None),
                        ~has_audio_reference(tenant_id, other_than_meeting=meeting_id),
                    )
                )
            )
            .scalars()
            .all()
        ):
            await retire_audio(session, chunk_audio)
    logger.info(
        "meeting audio assembled",
        extra={"extra_fields": {"meeting_id": str(meeting_id), "chunks": len(chunks)}},
    )
    return "assembled"
