from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AsrTranscriptRevision,
    AsrTranscriptRevisionSegment,
    Transcript,
    TranscriptRevision,
    Utterance,
)


def timestamp_source(rows: list[tuple[int, Any]]) -> str:
    sources = {
        str((segment.metadata or {}).get("timestamp_source") or "native")
        for _, segment in rows
    }
    if not sources:
        return "unknown"
    return next(iter(sources)) if len(sources) == 1 else "mixed"


async def activate_new(
    session: AsyncSession,
    *,
    call_id: UUID,
    tenant_id: UUID,
    rows: list[tuple[int, Any]],
    full_text: str,
    asr_model: str,
    asr_version: str,
    audio_channels: int,
    revision: AsrTranscriptRevision | None = None,
) -> tuple[Transcript, AsrTranscriptRevision]:
    now = datetime.now(UTC)
    if revision is None:
        revision = AsrTranscriptRevision(
            call_id=call_id,
            tenant_id=tenant_id,
            status="running",
            trigger="initial",
        )
        session.add(revision)
        await session.flush()
    revision.status = "succeeded"
    revision.full_text = full_text
    revision.asr_model = asr_model
    revision.asr_version = asr_version
    revision.speaker_mode = (
        "dual_channel"
        if audio_channels == 2
        else "mono_diarized"
        if any((segment.metadata or {}).get("speaker") is not None for _, segment in rows)
        else "mono_unknown"
    )
    revision.timestamp_source = timestamp_source(rows)
    revision.metrics = {"segments": len(rows), "audio_channels": audio_channels}
    revision.completed_at = now
    revision.activated_at = now
    await session.execute(
        delete(AsrTranscriptRevisionSegment).where(
            AsrTranscriptRevisionSegment.revision_id == revision.id
        )
    )
    for position, (channel, segment) in enumerate(rows):
        session.add(
            AsrTranscriptRevisionSegment(
                revision_id=revision.id,
                tenant_id=tenant_id,
                position=position,
                channel=channel,
                t_start_ms=segment.t_start_ms,
                t_end_ms=segment.t_end_ms,
                text=segment.text,
                confidence=segment.confidence,
                metadata_json=segment.metadata,
            )
        )
    await session.execute(
        delete(Utterance).where(Utterance.call_id == call_id, Utterance.tenant_id == tenant_id)
    )
    for channel, segment in rows:
        session.add(
            Utterance(
                call_id=call_id,
                tenant_id=tenant_id,
                channel=channel,
                t_start_ms=segment.t_start_ms,
                t_end_ms=segment.t_end_ms,
                text=segment.text,
                confidence=segment.confidence,
                metadata_json=segment.metadata,
            )
        )
    transcript = (
        await session.execute(
            select(Transcript).where(
                Transcript.call_id == call_id, Transcript.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if transcript is None:
        transcript = Transcript(
            call_id=call_id,
            tenant_id=tenant_id,
            full_text=full_text,
            asr_model=asr_model,
            asr_version=asr_version,
        )
        session.add(transcript)
    else:
        transcript.full_text = full_text
        transcript.asr_model = asr_model
        transcript.asr_version = asr_version
        transcript.corrected_text = None
        transcript.corrected_at = None
        transcript.active_revision_id = None
    transcript.active_asr_revision_id = revision.id
    await session.flush()
    return transcript, revision


async def activate_existing(
    session: AsyncSession,
    *,
    transcript: Transcript,
    revision: AsrTranscriptRevision,
) -> list[AsrTranscriptRevisionSegment]:
    rows = list(
        (
            await session.execute(
                select(AsrTranscriptRevisionSegment)
                .where(
                    AsrTranscriptRevisionSegment.revision_id == revision.id,
                    AsrTranscriptRevisionSegment.tenant_id == transcript.tenant_id,
                )
                .order_by(AsrTranscriptRevisionSegment.position)
            )
        ).scalars()
    )
    if revision.status != "succeeded" or not revision.full_text or not rows:
        raise ValueError("ASR transcript revision is not activatable")
    await session.execute(
        delete(Utterance).where(
            Utterance.call_id == transcript.call_id,
            Utterance.tenant_id == transcript.tenant_id,
        )
    )
    for row in rows:
        session.add(
            Utterance(
                call_id=transcript.call_id,
                tenant_id=transcript.tenant_id,
                channel=row.channel,
                t_start_ms=row.t_start_ms,
                t_end_ms=row.t_end_ms,
                text=row.text,
                confidence=row.confidence,
                metadata_json=row.metadata_json,
            )
        )
    transcript.full_text = revision.full_text
    transcript.asr_model = revision.asr_model or transcript.asr_model
    transcript.asr_version = revision.asr_version or transcript.asr_version
    transcript.active_asr_revision_id = revision.id
    correction = (
        await session.execute(
            select(TranscriptRevision)
            .where(
                TranscriptRevision.asr_revision_id == revision.id,
                TranscriptRevision.tenant_id == transcript.tenant_id,
                TranscriptRevision.status == "succeeded",
            )
            .order_by(TranscriptRevision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    transcript.active_revision_id = correction.id if correction else None
    transcript.corrected_text = correction.corrected_text if correction else None
    transcript.corrected_at = correction.completed_at if correction else None
    revision.activated_at = datetime.now(UTC)
    await session.flush()
    return rows
