from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Call
from app.services import processing_events

# Discrete call.status → baseline percent + Persian label. Workers overwrite these
# with finer values (per channel / chunk) while a stage is running.
STAGE_DEFAULTS: dict[str, tuple[int | None, str]] = {
    "received": (5, "فایل دریافت شد"),
    "reserved": (10, "اعتبار رزرو شد"),
    "stored": (15, "در صف پیاده‌سازی گفتار"),
    "transcribing": (20, "در حال پیاده‌سازی گفتار"),
    "transcribed": (55, "در صف تحلیل متن"),
    "emotion_queued": (50, "در صف تحلیل لحن صدا"),
    "emotion_analyzing": (52, "در حال تحلیل لحن صدا"),
    "analyzing": (60, "در حال تحلیل مکالمه"),
    "analyzed": (85, "تحلیل تمام شد"),
    "billed": (90, "در حال اطلاع‌رسانی"),
    "notified": (95, "اطلاع‌رسانی شد"),
    "complete": (100, "پردازش کامل شد"),
    "failed_retryable": (None, "خطای موقت؛ تلاش مجدد به‌زودی"),
    "failed_terminal": (None, "پردازش به‌خاطر خطا متوقف شد"),
    "canceled": (None, "لغو شده"),
}

PROCESSING_STATUSES = frozenset(
    {
        "received",
        "reserved",
        "stored",
        "transcribing",
        "transcribed",
        "emotion_queued",
        "emotion_analyzing",
        "analyzing",
        "analyzed",
        "billed",
        "notified",
        "failed_retryable",
    }
)


def lerp(start: int, end: int, current: int, total: int, *, finished: bool = False) -> int:
    """Map step `current` of `total` onto [start, end]. `current` is 1-based."""
    if total <= 0:
        return end if finished else start
    numerator = current if finished else max(current - 1, 0)
    fraction = min(max(numerator / total, 0.0), 1.0)
    return start + round((end - start) * fraction)


def values_for_status(status: str) -> dict[str, int | str]:
    """Column updates that travel with a status change. Failed states keep the last percent."""
    pct, detail = STAGE_DEFAULTS.get(status, (None, status))
    payload: dict[str, int | str] = {"progress_detail": detail}
    if pct is not None:
        payload["progress_pct"] = pct
    return payload


def resolve(status: str, pct: int | None, detail: str | None) -> tuple[int, str, bool]:
    """Fill in defaults so older rows without stored progress still render a bar."""
    default_pct, default_detail = STAGE_DEFAULTS.get(status, (0, status))
    resolved_pct = pct if pct is not None else (default_pct if default_pct is not None else 0)
    resolved_detail = detail or default_detail
    return resolved_pct, resolved_detail, status in PROCESSING_STATUSES


async def report(
    session: AsyncSession,
    *,
    call_id: UUID,
    tenant_id: UUID,
    pct: int,
    detail: str,
    kind: str = "pipeline",
) -> None:
    bounded_pct = max(0, min(pct, 100))
    await session.execute(
        update(Call)
        .where(Call.id == call_id, Call.tenant_id == tenant_id)
        .values(
            progress_pct=bounded_pct,
            progress_detail=detail[:500],
            updated_at=datetime.now(UTC),
        )
    )
    await processing_events.record(
        session,
        tenant_id=tenant_id,
        call_id=call_id,
        kind=kind,
        message=detail,
        progress_pct=bounded_pct,
        status="running",
    )
