"""Whole-meeting WAV of a text meeting, assembled from the chunks the app uploaded.

Text meetings are never transcribed on the server: the audio is only stored so the panel can play
it. The chunks are joined into one WAV (the object the panel streams with `Range`) and the chunk
copies are then removed to halve the stored bytes.
"""

from __future__ import annotations

import logging
import struct
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db import session_scope
from app.models import AudioObject, Meeting, MeetingChunk, Tenant
from app.services.audio import probe_wav_file
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
_HEADER_BYTES = 44


def audio_object_key(tenant_id: UUID, meeting_id: UUID) -> str:
    return f"{tenant_id}/meetings/{meeting_id}/full.wav"


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
    """Join the chunks in order into one WAV and attach it to the meeting; idempotent."""
    storage = get_storage()
    async with session_scope(tenant_id) as session:
        meeting = await session.get(Meeting, meeting_id)
        if meeting is None:
            return "missing"
        if meeting.audio_id is not None:
            return "done"
        chunks = list(
            (
                await session.execute(
                    select(MeetingChunk)
                    .where(
                        MeetingChunk.meeting_id == meeting_id, MeetingChunk.audio_id.is_not(None)
                    )
                    .order_by(MeetingChunk.seq)
                )
            )
            .scalars()
            .all()
        )
        if not chunks:
            return "no_chunks"
        keys = []
        for chunk in chunks:
            audio = await session.get(AudioObject, chunk.audio_id)
            if audio is not None and audio.deleted_at is None:
                keys.append(audio.object_key)
        tenant = await session.get(Tenant, tenant_id)
        retention_days = tenant.audio_retention_days if tenant is not None else 30

    if not keys:
        return "no_chunks"
    with tempfile.TemporaryDirectory(prefix="meeting-audio-") as tmp:
        path = Path(tmp) / "full.wav"
        total = 0
        with path.open("wb") as out:
            out.write(b"\0" * _HEADER_BYTES)
            for key in keys:
                data = wav_data(await storage.get(key))
                out.write(data)
                total += len(data)
            out.seek(0)
            out.write(wav_header(total))
        probe = await probe_wav_file(path)
        key = audio_object_key(tenant_id, meeting_id)
        await storage.put_path(key, path)

    async with session_scope(tenant_id) as session:
        meeting = await session.get(Meeting, meeting_id)
        if meeting is None or meeting.audio_id is not None:
            await storage.delete(key)
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
        # The joined file replaces the chunk copies.
        now = datetime.now(UTC)
        for chunk_audio in (
            (
                await session.execute(
                    select(AudioObject)
                    .join(MeetingChunk, MeetingChunk.audio_id == AudioObject.id)
                    .where(MeetingChunk.meeting_id == meeting_id, AudioObject.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        ):
            await storage.delete(chunk_audio.object_key)
            chunk_audio.deleted_at = now
    logger.info(
        "meeting audio assembled",
        extra={"extra_fields": {"meeting_id": str(meeting_id), "chunks": len(keys)}},
    )
    return "assembled"
