from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import AsrTranscriptRevision, AudioObject, Call, Job, Transcript, TranscriptRevision
from app.services import outbox, processing_events
from app.services.platform import capability_model, effective_models

RETRANSCRIPTION_READY_STATUSES = ("complete", "failed_terminal")


async def ensure_no_active(session: AsyncSession, call: Call) -> None:
    active = (
        await session.execute(
            select(AsrTranscriptRevision.id)
            .where(
                AsrTranscriptRevision.call_id == call.id,
                AsrTranscriptRevision.tenant_id == call.tenant_id,
                AsrTranscriptRevision.status.in_(("queued", "running")),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        raise ApiError("call_retranscription_busy", "صبر کنید تا پردازش فعال این تماس تمام شود.")


async def stage(
    session: AsyncSession,
    call: Call,
    *,
    campaign: str | None = None,
) -> tuple[UUID, UUID] | None:
    """Stage an unbilled revision while the caller holds the call row lock."""
    call_id, tenant_id = call.id, call.tenant_id
    transcript = await session.get(Transcript, call_id)
    if transcript is None:
        raise ApiError("invalid_request", "برای این تماس هنوز نسخه متنی وجود ندارد.")
    audio = (
        await session.execute(
            select(AudioObject).where(
                AudioObject.id == call.audio_id,
                AudioObject.tenant_id == tenant_id,
                AudioObject.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if audio is None:
        raise ApiError("not_found", "فایل صوتی این تماس در دسترس نیست.")
    await ensure_no_active(session, call)
    if call.status not in RETRANSCRIPTION_READY_STATUSES:
        raise ApiError("call_retranscription_busy", "صبر کنید تا پردازش فعال این تماس تمام شود.")
    correction = await session.scalar(
        select(TranscriptRevision.id)
        .where(
            TranscriptRevision.call_id == call_id,
            TranscriptRevision.tenant_id == tenant_id,
            TranscriptRevision.status.in_(("queued", "running", "validating")),
        )
        .limit(1)
    )
    if correction is not None:
        raise ApiError("call_retranscription_busy", "صبر کنید تا اصلاح متن این تماس تمام شود.")
    previous_status = call.status
    if campaign is not None:
        existing = await session.scalar(
            select(AsrTranscriptRevision.id)
            .where(
                AsrTranscriptRevision.call_id == call_id,
                AsrTranscriptRevision.tenant_id == tenant_id,
                AsrTranscriptRevision.metrics["batch_campaign"].as_string() == campaign,
            )
            .limit(1)
        )
        if existing is not None:
            return None
    models = await effective_models(session)
    revision = AsrTranscriptRevision(
        call_id=call_id,
        tenant_id=tenant_id,
        status="queued",
        trigger="manual",
        metrics={
            "previous_status": previous_status,
            "previous_error_code": call.error_code,
            "previous_progress_pct": call.progress_pct,
            "previous_progress_detail": call.progress_detail,
            **({"batch_campaign": campaign} if campaign is not None else {}),
        },
        ai_provider=models["asr_ai_provider"],
        asr_model=capability_model(models, "asr"),
    )
    session.add(revision)
    job = Job(
        tenant_id=tenant_id,
        call_id=call_id,
        kind="asr",
        status="queued",
        attempt=0,
        run_after=datetime.now(UTC),
        ai_provider=models["asr_ai_provider"],
        ai_model=capability_model(models, "asr"),
    )
    session.add(job)
    await session.flush()
    await processing_events.record(
        session,
        tenant_id=tenant_id,
        call_id=call_id,
        kind="asr",
        status="queued",
        progress_pct=5,
        message="ساخت نسخه جدید متن بدون کسر اعتبار در صف قرار گرفت",
        step_key=f"{job.id}:queued:0",
    )
    outbox_id = await outbox.stage_job(
        session,
        job_id=job.id,
        tenant_id=tenant_id,
        call_id=call_id,
        kind="asr",
        recovery=True,
        retranscription=True,
        previous_status=previous_status,
        asr_revision_id=revision.id,
    )
    return revision.id, outbox_id
