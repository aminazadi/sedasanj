"""Weighted progress and the user-visible timeline of a meeting."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Meeting, MeetingEvent
from app.services.processing_events import sanitize_detail

# Share of the overall progress bar per stage (percent).
WEIGHT_TRANSCRIPTION = 75
WEIGHT_SPEAKERS = 5
WEIGHT_MINUTES = 20

STAGE_LABELS: dict[str, str] = {
    "receiving": "در حال دریافت صدای جلسه",
    "processing": "در حال پردازش جلسه",
    "transcribing": "در حال پیاده‌سازی گفتار",
    "speakers": "در حال تفکیک گوینده‌ها",
    "minutes": "در حال تهیه صورت‌جلسه",
    "complete": "پردازش جلسه کامل شد",
    "failed_retryable": "خطای موقت؛ تلاش مجدد به‌زودی",
    "failed_terminal": "پردازش جلسه به‌خاطر خطا متوقف شد",
    "canceled": "جلسه لغو شد",
}


def compute_progress(
    *,
    total_chunks: int | None,
    received_chunks: int,
    processed_chunks: int,
    speakers_done: bool = False,
    minutes_fraction: float = 0.0,
) -> int:
    """Weighted percent: 75% transcription, 5% speakers, 20% minutes."""
    denominator = total_chunks if total_chunks else max(received_chunks, 1)
    transcription = min(processed_chunks / denominator, 1.0) * WEIGHT_TRANSCRIPTION
    speakers = WEIGHT_SPEAKERS if speakers_done else 0
    minutes = min(max(minutes_fraction, 0.0), 1.0) * WEIGHT_MINUTES
    return max(0, min(100, int(transcription + speakers + minutes)))


def set_stage(meeting: Meeting, stage: str, *, progress_pct: int | None = None) -> None:
    meeting.progress_detail = STAGE_LABELS.get(stage, stage)
    if progress_pct is not None:
        meeting.progress_pct = max(0, min(100, progress_pct))


async def record_event(
    session: AsyncSession,
    meeting: Meeting,
    *,
    step_key: str,
    kind: str,
    status: str,
    detail: str | None = None,
) -> None:
    """Idempotent on (meeting, step_key); detail is scrubbed of secrets before storage."""
    await session.execute(
        pg_insert(MeetingEvent)
        .values(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            step_key=step_key,
            kind=kind,
            status=status,
            detail=sanitize_detail(detail),
        )
        .on_conflict_do_nothing(index_elements=["meeting_id", "step_key"])
    )
