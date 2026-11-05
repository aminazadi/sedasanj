"""Meeting worker: builds the minutes of text meetings and joins their audio (`q:meeting`)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from arq import Retry, cron
from arq.connections import RedisSettings
from arq.worker import func
from sqlalchemy import exists, select

from app.config import get_settings
from app.db import dispose_engine, session_scope
from app.logging import configure_logging, log_context
from app.metrics import start_metrics_server
from app.models import Meeting, MeetingChunk, MeetingMinutes, Tenant
from app.services import queue
from app.services.meeting_audio import assemble_meeting_audio
from app.services.meeting_minutes import MinutesRetryable, generate_minutes

logger = logging.getLogger(__name__)

MAX_TRIES = 3
RETRY_DELAY_SECONDS = 60
# A processing text meeting with no minutes after this long lost its job (enqueue failed or the
# worker died); the reconciler queues it again.
STALE_AFTER = timedelta(minutes=5)


async def reanalyze_meeting_minutes(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    meeting_id = UUID(str(payload["meeting_id"]))
    version = int(payload.get("version") or 0)
    attempt = int(ctx.get("job_try", 1))
    log_context(tenant_id=str(tenant_id))
    try:
        return await generate_minutes(
            tenant_id, meeting_id, version, final_attempt=attempt >= MAX_TRIES
        )
    except MinutesRetryable as exc:
        raise Retry(defer=RETRY_DELAY_SECONDS * attempt) from exc


async def assemble_meeting_audio_job(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Join the uploaded chunks of a text meeting into the WAV the panel plays."""
    tenant_id = UUID(str(payload["tenant_id"]))
    log_context(tenant_id=str(tenant_id))
    return await assemble_meeting_audio(tenant_id, UUID(str(payload["meeting_id"])))


async def transcribe_meeting_chunk(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Audio meetings are not transcribed on the server any more: the app sends text."""
    logger.warning(
        "audio meeting chunk ignored; update the Jalase-Negar app to send text",
        extra={"extra_fields": {"meeting_id": str(payload.get("meeting_id"))}},
    )
    return "ignored"


async def requeue_stale_minutes() -> int:
    """Queue minutes for text meetings that are processing without a job; returns the count."""
    cutoff = datetime.now(UTC) - STALE_AFTER
    async with session_scope(None, staff=True) as session:
        tenant_ids = list((await session.execute(select(Tenant.id))).scalars().all())
    queued = 0
    for tenant_id in tenant_ids:
        async with session_scope(tenant_id) as session:
            meeting_ids = list(
                (
                    await session.execute(
                        select(Meeting.id).where(
                            Meeting.input_kind == "text",
                            Meeting.status == "processing",
                            Meeting.updated_at < cutoff,
                            ~exists().where(MeetingMinutes.meeting_id == Meeting.id),
                        )
                    )
                )
                .scalars()
                .all()
            )
        for meeting_id in meeting_ids:
            await queue.get_queue().enqueue(
                queue.QUEUE_MEETING,
                queue.JOB_MEETING_MINUTES,
                {"tenant_id": str(tenant_id), "meeting_id": str(meeting_id), "version": 1},
                job_id=f"meeting-minutes:{meeting_id}:reconcile:{int(cutoff.timestamp()) // 300}",
            )
            queued += 1
    return queued


async def requeue_unassembled_audio() -> int:
    """Queue the audio join for text meetings whose chunks were never joined."""
    cutoff = datetime.now(UTC) - STALE_AFTER
    async with session_scope(None, staff=True) as session:
        tenant_ids = list((await session.execute(select(Tenant.id))).scalars().all())
    queued = 0
    for tenant_id in tenant_ids:
        async with session_scope(tenant_id) as session:
            meeting_ids = list(
                (
                    await session.execute(
                        select(Meeting.id).where(
                            Meeting.input_kind == "text",
                            Meeting.status.in_(("processing", "complete")),
                            Meeting.audio_id.is_(None),
                            Meeting.total_chunks > 0,
                            Meeting.updated_at < cutoff,
                            exists().where(
                                MeetingChunk.meeting_id == Meeting.id,
                                MeetingChunk.audio_id.is_not(None),
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
        for meeting_id in meeting_ids:
            await queue.get_queue().enqueue(
                queue.QUEUE_MEETING,
                queue.JOB_MEETING_AUDIO,
                {"tenant_id": str(tenant_id), "meeting_id": str(meeting_id)},
                job_id=f"meeting-audio:{meeting_id}:reconcile:{int(cutoff.timestamp()) // 300}",
            )
            queued += 1
    return queued


async def reconciler_cron(ctx: dict[str, Any]) -> str:
    try:
        queued = await requeue_stale_minutes() + await requeue_unassembled_audio()
    except Exception:  # noqa: BLE001 - the next tick retries
        logger.warning("meeting reconciler failed", exc_info=True)
        return "failed"
    if queued:
        logger.warning(
            "requeued stale meeting minutes", extra={"extra_fields": {"meetings": queued}}
        )
    return f"requeued={queued}"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging("worker-meeting", settings.log_level)
    start_metrics_server(settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    await queue.get_queue().close()
    await dispose_engine()


class WorkerSettings:
    job_serializer = queue.job_serializer
    job_deserializer = queue.job_deserializer
    # Handler names must match the JOB_* constants the API enqueues.
    functions = [
        func(reanalyze_meeting_minutes, name=queue.JOB_MEETING_MINUTES),
        func(assemble_meeting_audio_job, name=queue.JOB_MEETING_AUDIO),
        func(transcribe_meeting_chunk, name=queue.JOB_MEETING_CHUNK),
    ]
    cron_jobs = [cron(reconciler_cron, minute={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57})]
    queue_name = queue.QUEUE_MEETING
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    max_tries = MAX_TRIES
    job_timeout = 1800
    keep_result = 3600
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
