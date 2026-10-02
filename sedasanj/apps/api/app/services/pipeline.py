from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.metrics import job_wait_seconds
from app.models import Call, Job, Tenant
from app.services import billing, outbox, processing_events, progress

logger = logging.getLogger(__name__)

# §5 retry policy: (max attempts, base backoff seconds, factor)
RETRY_POLICY: dict[str, tuple[int, int, int]] = {
    "asr": (5, 5, 2),
    "emotion": (3, 10, 2),
    "correction": (3, 10, 2),
    "llm": (4, 10, 2),
    "notify": (8, 15, 2),
}


# §11 reanalysis may start from any settled state; the call returns to it afterwards.
REANALYSIS_STATES: tuple[str, ...] = (
    "transcribed",
    "analyzed",
    "analyzing",
    "billed",
    "notified",
    "complete",
    "failed_terminal",
)


def backoff_for(kind: str, attempt: int) -> timedelta:
    _, base, factor = RETRY_POLICY[kind]
    return timedelta(seconds=base * (factor**attempt))


async def claim_call(
    session: AsyncSession,
    call_id: UUID,
    *,
    tenant_id: UUID,
    expected: str | tuple[str, ...],
    next_status: str,
) -> Call | None:
    """Conditional status UPDATE. Zero rows means another worker owns the job (§6)."""
    expected_tuple = (expected,) if isinstance(expected, str) else expected
    result = await session.execute(
        update(Call)
        .where(
            Call.id == call_id,
            Call.tenant_id == tenant_id,
            Call.status.in_(expected_tuple),
        )
        .values(
            status=next_status,
            error_code=None,
            updated_at=datetime.now(UTC),
            **progress.values_for_status(next_status),
        )
        .returning(Call.id)
    )
    if result.scalar_one_or_none() is None:
        return None
    return (
        await session.execute(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def lock_job_for_claim(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    kind: str,
    expected: tuple[str, ...],
) -> Job | None:
    """Lock the newest job and return it only while its state is claimable.

    The call row alone cannot distinguish a legitimate reanalysis queued by the
    API from a duplicate delivery: both observe ``call.status == analyzing``.
    Serializing on the job row gives one worker ownership before it is allowed
    to accept that in-progress call state. Recovery may explicitly include
    ``running`` after the stale-worker cutoff; normal deliveries must not.
    """
    job = (
        await session.execute(
            select(Job)
            .where(Job.tenant_id == tenant_id, Job.call_id == call_id, Job.kind == kind)
            .order_by(Job.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None or job.status not in expected:
        return None
    return job


async def mark_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    kind: str,
    status: str,
    attempt: int | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    run_after: datetime | None = None,
) -> Job:
    job = (
        await session.execute(
            select(Job)
            .where(Job.tenant_id == tenant_id, Job.call_id == call_id, Job.kind == kind)
            .order_by(Job.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        job = Job(tenant_id=tenant_id, call_id=call_id, kind=kind, status=status, attempt=0)
        session.add(job)
        await session.flush()
    job.status = status
    if attempt is not None:
        job.attempt = attempt
    job.error_code = error_code
    job.error_detail = (error_detail or "")[:2000] or None
    if run_after is not None:
        job.run_after = run_after
    if status == "queued":
        job.queued_at = datetime.now(UTC)
        job.started_at = None
        job.provider_submitted_at = None
        job.completed_at = None
    if status == "running":
        now = datetime.now(UTC)
        job.locked_at = now
        job.started_at = now
        job_wait_seconds.labels(kind=kind).observe(max((now - job.run_after).total_seconds(), 0.0))
    if status in {"succeeded", "failed_terminal"}:
        job.completed_at = datetime.now(UTC)
    level = (
        "success"
        if status == "succeeded"
        else "error"
        if status == "failed_terminal"
        else "warning"
        if status == "failed_retryable"
        else "info"
    )
    step_labels = {
        "asr": "تبدیل گفتار",
        "emotion": "تحلیل لحن صدا",
        "correction": "تصحیح هوشمند متن",
        "llm": "تحلیل هوشمند",
        "notify": "اطلاع‌رسانی",
    }
    step_label = step_labels[kind]
    status_messages = {
        "queued": f"{step_label} در صف پردازش قرار گرفت",
        "running": f"{step_label} در حال انجام است",
        "succeeded": f"{step_label} با موفقیت انجام شد",
        "failed_retryable": f"{step_label} خطا داد و برای تلاش مجدد زمان‌بندی شد",
        "failed_terminal": f"{step_label} به‌دلیل خطا متوقف شد",
    }
    await processing_events.record(
        session,
        tenant_id=tenant_id,
        call_id=call_id,
        kind=kind,
        level=level,
        status=status,
        message=status_messages.get(status, status),
        error_code=error_code,
        error_detail=error_detail,
        step_key=f"{job.id}:{status}:{job.attempt}",
    )
    await session.flush()
    return job


async def handle_failure(
    *,
    tenant_id: UUID,
    call_id: UUID,
    kind: str,
    error_code: str,
    error_detail: str,
    analysis_run_id: UUID | None = None,
    correction_run_id: UUID | None = None,
    reanalysis: bool = False,
    previous_status: str | None = None,
    event: str | None = None,
    retryable: bool | None = None,
    max_attempts_override: int | None = None,
) -> bool:
    """§6 step 3: back off and requeue, or go terminal and release the hold.

    This function is the only place that reschedules work, so callers must not enqueue again.
    Notification failures and reanalysis never move the call itself: the analysis is already
    paid for and stored, so only the job row is marked and eventually dead-lettered.

    Returns True when the job was rescheduled.
    """
    configured_max_attempts, _, _ = RETRY_POLICY[kind]
    max_attempts = max_attempts_override or configured_max_attempts
    touches_call = kind in {"asr", "correction", "llm"} and not reanalysis
    outbox_id: UUID | None = None
    async with session_scope(tenant_id) as session:
        job = (
            await session.execute(
                select(Job)
                .where(
                    Job.tenant_id == tenant_id,
                    Job.call_id == call_id,
                    Job.kind == kind,
                )
                .order_by(Job.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        attempt = (job.attempt if job else 0) + 1
        retry = (
            attempt < max_attempts
            if retryable is None
            else (bool(retryable) and attempt < max_attempts)
        )
        delay = backoff_for(kind, attempt)
        job = await mark_job(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind=kind,
            status="failed_retryable" if retry else "failed_terminal",
            attempt=attempt,
            error_code=error_code,
            error_detail=error_detail,
            run_after=datetime.now(UTC) + delay,
        )
        if touches_call:
            next_status = "failed_retryable" if retry else "failed_terminal"
            await session.execute(
                update(Call)
                .where(Call.id == call_id, Call.tenant_id == tenant_id)
                .values(
                    status=next_status,
                    error_code=error_code,
                    updated_at=datetime.now(UTC),
                    **progress.values_for_status(next_status),
                )
            )
        elif kind == "emotion" and retry:
            await session.execute(
                update(Call)
                .where(Call.id == call_id, Call.tenant_id == tenant_id)
                .values(
                    status="emotion_queued",
                    error_code=None,
                    updated_at=datetime.now(UTC),
                    **progress.values_for_status("emotion_queued"),
                )
            )
        if not retry and kind in ("asr", "correction", "llm") and not reanalysis:
            await billing.release(session, tenant_id=tenant_id, call_id=call_id)
        if retry and job is not None:
            outbox_id = await outbox.stage_job(
                session,
                job_id=job.id,
                tenant_id=tenant_id,
                call_id=call_id,
                kind=kind,
                analysis_run_id=analysis_run_id,
                correction_run_id=correction_run_id,
                reanalysis=reanalysis,
                previous_status=previous_status,
                event=event,
                available_at=datetime.now(UTC) + delay,
            )
        elif touches_call:
            outbox_id = await outbox.stage(
                session,
                tenant_id=tenant_id,
                queue_name="q:notify",
                function_name="deliver_event",
                payload={
                    "tenant_id": str(tenant_id),
                    "call_id": str(call_id),
                    "event": "call.failed",
                },
            )

    if outbox_id is not None:
        try:
            await outbox.dispatch_one(outbox_id)
        except Exception:
            logger.exception(
                "immediate retry dispatch failed; durable dispatcher will retry",
                extra={"extra_fields": {"call_id": str(call_id), "kind": kind}},
            )
    logger.warning(
        "job failed",
        extra={
            "extra_fields": {
                "kind": kind,
                "call_id": str(call_id),
                "error_code": error_code,
                "retry": retry,
            }
        },
    )
    return retry


async def concurrency_slot_free(
    session: AsyncSession,
    tenant_id: UUID,
    limit: int,
    *,
    kind: str,
) -> bool:
    """Serialize capacity claims per tenant while keeping ASR and LLM quotas separate."""
    await session.execute(
        select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
    )
    running = (
        await session.execute(
            select(func.count(Job.id)).where(
                Job.tenant_id == tenant_id,
                Job.status == "running",
                Job.kind == kind,
            )
        )
    ).scalar_one()
    return int(running) < limit


async def global_analysis_slot_free(
    session: AsyncSession,
    *,
    job_id: UUID,
    limit: int,
) -> bool:
    """Reserve a slot for one whole call analysis, from claim through terminal completion.

    The LLM job remains ``running`` while durable provider steps are submitted and
    polled, so it continues to consume this slot until the call is finalized or
    fails terminally. The advisory lock makes the count and oldest-job decision
    one atomic admission operation across every worker process.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(918273645)"))
    running = (
        await session.execute(
            select(func.count(Job.id)).where(Job.kind == "llm", Job.status == "running")
        )
    ).scalar_one()
    if int(running) >= limit:
        return False
    oldest = (
        await session.execute(
            select(Job.id)
            .where(Job.kind == "llm", Job.status.in_(("queued", "failed_retryable")))
            .order_by(Job.queued_at.asc(), Job.created_at.asc(), Job.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return oldest == job_id
