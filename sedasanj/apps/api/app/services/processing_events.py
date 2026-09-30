from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProcessingEvent

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+"),
    re.compile(
        r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret|password)=)[^&#\s]+"
    ),
    re.compile(r"(?i)(https?://[^\s:/]+:)[^@\s]+@"),
)


def sanitize_detail(value: str | None, *, limit: int = 2000) -> str | None:
    if not value:
        return None
    sanitized = value.replace("\x00", " ")
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
    return sanitized[:limit]


async def record(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    kind: str,
    message: str,
    level: str = "info",
    status: str | None = None,
    progress_pct: int | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    step_key: str | None = None,
) -> ProcessingEvent:
    """Create one visible entry per step and update it until that step settles."""
    existing: ProcessingEvent | None = None
    if step_key is not None:
        existing = (
            await session.execute(
                select(ProcessingEvent)
                .where(
                    ProcessingEvent.call_id == call_id,
                    ProcessingEvent.tenant_id == tenant_id,
                    ProcessingEvent.step_key == step_key,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
    else:
        # Fine-grained progress belongs to the currently running step, not a new timeline row.
        existing = (
            await session.execute(
                select(ProcessingEvent)
                .where(
                    ProcessingEvent.call_id == call_id,
                    ProcessingEvent.tenant_id == tenant_id,
                    ProcessingEvent.kind == kind,
                    ProcessingEvent.step_key.is_(None),
                    ProcessingEvent.status.in_(("queued", "running")),
                )
                .order_by(ProcessingEvent.created_at.desc(), ProcessingEvent.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
    if existing is not None:
        existing.level = level
        existing.status = status
        existing.progress_pct = (
            max(0, min(progress_pct, 100)) if progress_pct is not None else None
        )
        existing.message = message[:500]
        existing.error_code = error_code
        existing.error_detail = sanitize_detail(error_detail)
        await session.flush()
        return existing
    event = ProcessingEvent(
        tenant_id=tenant_id,
        call_id=call_id,
        kind=kind,
        level=level,
        status=status,
        progress_pct=(max(0, min(progress_pct, 100)) if progress_pct is not None else None),
        message=message[:500],
        error_code=error_code,
        error_detail=sanitize_detail(error_detail),
        step_key=step_key,
    )
    session.add(event)
    await session.flush()
    return event
