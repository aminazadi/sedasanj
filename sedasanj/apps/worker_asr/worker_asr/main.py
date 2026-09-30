from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import (
    dispose_engine,
    operational_tenant_ids,
    resolve_tenant_for_call,
    session_scope,
)
from app.logging import configure_logging, log_context
from app.metrics import asr_seconds_processed, start_metrics_server
from app.models import AnalysisRun, AudioObject, Call, Job, Tenant, Transcript, Utterance
from app.services import outbox, pipeline, processing_events, progress, queue
from app.services.audio import (
    AudioPreprocessingConfig,
    preprocess_mono_audio,
    probe_wav_file,
    resample_to_16k,
    split_channels,
)
from app.services.platform import (
    effective_extract_prompt,
    effective_models,
    resolve_provider_settings,
)
from app.services.provider_errors import classify_failure
from app.services.storage import get_storage
from worker_asr.engine import AsrEngine, AsrSegment, build_engine

logger = logging.getLogger(__name__)

CHANNEL_LABELS = {0: "caller", 1: "agent"}
TURN_MERGE_GAP_MS = 1_200


def _clean_segment_text(text: str) -> str:
    return " ".join(text.split()).strip()


def consolidate_segments(rows: list[tuple[int, AsrSegment]]) -> list[tuple[int, AsrSegment]]:
    """Create readable chronological turns without discarding cross-talk.

    Some providers emit word-sized segments. Consecutive segments from the
    same channel are one turn when there is no intervening speaker and the
    silence is short. Exact repeated segments are suppressed, while overlapping
    speech from the other channel is intentionally preserved.
    """
    ordered = sorted(rows, key=lambda item: (item[1].t_start_ms, item[0], item[1].t_end_ms))
    merged: list[tuple[int, AsrSegment]] = []
    for channel, segment in ordered:
        text = _clean_segment_text(segment.text)
        if not text:
            continue
        current = AsrSegment(
            t_start_ms=max(segment.t_start_ms, 0),
            t_end_ms=max(segment.t_end_ms, segment.t_start_ms, 0),
            text=text,
        )
        if not merged:
            merged.append((channel, current))
            continue
        previous_channel, previous = merged[-1]
        if (
            previous_channel == channel
            and current.t_start_ms <= previous.t_end_ms + TURN_MERGE_GAP_MS
        ):
            overlaps = current.t_start_ms <= previous.t_end_ms
            if overlaps and (
                current.text == previous.text or previous.text.endswith(current.text)
            ):
                combined_text = previous.text
            elif overlaps and current.text.startswith(previous.text):
                combined_text = current.text
            else:
                combined_text = f"{previous.text} {current.text}"
            merged[-1] = (
                channel,
                AsrSegment(
                    t_start_ms=previous.t_start_ms,
                    t_end_ms=max(previous.t_end_ms, current.t_end_ms),
                    text=combined_text,
                ),
            )
            continue
        merged.append((channel, current))
    return merged


def _stamp(ms: int) -> str:
    total = max(ms, 0) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def build_full_text(rows: list[tuple[int, AsrSegment]]) -> str:
    """§9.1 step 4 transcript layout: `[caller 00:00] …`."""
    lines: list[str] = []
    for channel, segment in sorted(rows, key=lambda item: (item[1].t_start_ms, item[0])):
        label = CHANNEL_LABELS.get(channel)
        prefix = f"[{label:<6} {_stamp(segment.t_start_ms)}] " if label else ""
        lines.append(f"{prefix}{segment.text}".strip())
    return "\n".join(lines)


async def _load_or_create_analysis_run(
    session: AsyncSession, call_id: UUID, tenant_id: UUID
) -> AnalysisRun:
    run: AnalysisRun | None = (
        await session.execute(
            select(AnalysisRun)
            .where(
                AnalysisRun.call_id == call_id,
                AnalysisRun.tenant_id == tenant_id,
                AnalysisRun.status == "pending",
            )
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is not None:
        run.status = "queued"
        return run
    models = await effective_models(session)
    run = AnalysisRun(
        call_id=call_id,
        tenant_id=tenant_id,
        llm_model=models["llm_model"],
        prompt_version=models["prompt_version"],
        system_prompt=await effective_extract_prompt(session, models["prompt_version"]),
        status="queued",
    )
    session.add(run)
    return run


async def _transcribe_tracks(
    engine: AsrEngine,
    original: Path,
    scratch: Path,
    channels: int,
    preprocessing: AudioPreprocessingConfig | None = None,
) -> list[tuple[int, AsrSegment]]:
    preprocessing = preprocessing or AudioPreprocessingConfig()
    rows: list[tuple[int, AsrSegment]] = []
    if channels == 2:
        left, right = scratch / "left.wav", scratch / "right.wav"
        await split_channels(original, left, right)
        if preprocessing.enabled:
            left_ready = scratch / "left-preprocessed.wav"
            right_ready = scratch / "right-preprocessed.wav"
            await asyncio.gather(
                preprocess_mono_audio(left, left_ready, preprocessing),
                preprocess_mono_audio(right, right_ready, preprocessing),
            )
        else:
            left_ready, right_ready = left, right
        left_segments, right_segments = await asyncio.gather(
            engine.transcribe(left_ready),
            engine.transcribe(right_ready),
        )
        rows.extend((0, segment) for segment in left_segments)
        rows.extend((1, segment) for segment in right_segments)
    else:
        mono = scratch / "mono16k.wav"
        if preprocessing.enabled:
            await preprocess_mono_audio(original, mono, preprocessing)
        else:
            await resample_to_16k(original, mono)
        rows.extend((0, segment) for segment in await engine.transcribe(mono))
    return [row for row in rows if row[1].text]


async def _engine_for_job(
    ctx: dict[str, Any], session: AsyncSession
) -> tuple[AsrEngine, AudioPreprocessingConfig]:
    """Remote engines rebuild per job so admin model/API-key changes apply immediately."""
    runtime = await resolve_provider_settings(session)
    if runtime.asr_engine in {"voicesanj", "whisper"}:
        engine = build_engine(runtime)
    else:
        local_engine = ctx.get("engine")
        if not isinstance(local_engine, AsrEngine):
            raise RuntimeError("local ASR engine was not initialized")
        engine = local_engine
        engine.model_name = runtime.asr_model_name
    preprocessing = AudioPreprocessingConfig(
        enabled=runtime.audio_preprocessing_enabled,
        denoiser_model=runtime.audio_denoiser_model,
        enhancement_model=runtime.audio_enhancement_model,
    )
    preprocessing.validate()
    return engine, preprocessing


async def transcribe_call(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    call_id = UUID(str(payload["call_id"]))
    recovery = bool(payload.get("recovery", False))
    tenant_hint = UUID(str(payload["tenant_id"])) if payload.get("tenant_id") else None
    tenant_id = await resolve_tenant_for_call(call_id, tenant_hint)
    if tenant_id is None:
        return "missing"
    async with session_scope(tenant_id) as session:
        call = await session.get(Call, call_id)
        if call is None:
            return "missing"
        tenant = await session.get(Tenant, tenant_id)
        concurrency_limit = min(
            tenant.max_concurrent_jobs if tenant else get_settings().max_concurrent_asr_jobs,
            get_settings().max_concurrent_asr_jobs,
        )
    log_context(tenant_id=str(tenant_id), call_id=str(call_id))

    deferred_outbox_id: UUID | None = None
    async with session_scope(tenant_id) as session:
        if not await pipeline.concurrency_slot_free(
            session, tenant_id, concurrency_limit, kind="asr"
        ):
            job = (
                await session.execute(
                    select(Job)
                    .where(Job.tenant_id == tenant_id, Job.call_id == call_id, Job.kind == "asr")
                    .order_by(Job.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if job is None:
                job = await pipeline.mark_job(
                    session,
                    tenant_id=tenant_id,
                    call_id=call_id,
                    kind="asr",
                    status="queued",
                )
            deferred_outbox_id = await outbox.stage_job(
                session,
                job_id=job.id,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="asr",
                recovery=recovery,
                available_at=datetime.now(UTC) + timedelta(seconds=30),
            )
        else:
            claimed = await pipeline.claim_call(
                session,
                call_id,
                tenant_id=tenant_id,
                expected=("stored", "failed_retryable", "transcribing")
                if recovery
                else ("stored", "failed_retryable"),
                next_status="transcribing",
            )
            if claimed is None:
                logger.info("asr job already owned elsewhere")
                return "skipped"
            audio = (
                (
                    await session.execute(
                        select(AudioObject).where(
                            AudioObject.id == claimed.audio_id,
                            AudioObject.tenant_id == tenant_id,
                        )
                    )
                ).scalar_one_or_none()
                if claimed.audio_id
                else None
            )
            if audio is None:
                raise RuntimeError("call has no audio object")
            object_key = audio.object_key
            audio_channels = audio.channels
            await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="asr", status="running"
            )

    if deferred_outbox_id is not None:
        await outbox.dispatch_one(deferred_outbox_id)
        return "deferred"

    try:
        async with session_scope(None, staff=True) as session:
            engine, preprocessing = await _engine_for_job(ctx, session)
        if preprocessing.enabled:
            async with session_scope(tenant_id) as session:
                await progress.report(
                    session,
                    call_id=call_id,
                    tenant_id=tenant_id,
                    pct=20,
                    detail="در حال حذف نویز و بهبود کیفیت صوت",
                    kind="asr",
                )
        with tempfile.TemporaryDirectory(prefix="cbi-asr-") as tmp:
            scratch = Path(tmp)
            original = scratch / "original.wav"
            original.write_bytes(await get_storage().get(object_key))
            probe = await probe_wav_file(original)
            rows = consolidate_segments(
                await _transcribe_tracks(
                    engine,
                    original,
                    scratch,
                    audio_channels,
                    preprocessing,
                )
            )

        full_text = build_full_text(rows)
        if not full_text:
            raise RuntimeError("ASR produced no text")

        async with session_scope(tenant_id) as session:
            await session.execute(
                delete(Utterance).where(
                    Utterance.call_id == call_id, Utterance.tenant_id == tenant_id
                )
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
                    )
                )
            existing = (
                await session.execute(
                    select(Transcript).where(
                        Transcript.call_id == call_id, Transcript.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    Transcript(
                        call_id=call_id,
                        tenant_id=tenant_id,
                        full_text=full_text,
                        asr_model=engine.model_name,
                        asr_version=f"{engine.model_version}|{preprocessing.identity}",
                    )
                )
            else:
                existing.full_text = full_text
                existing.asr_model = engine.model_name
                existing.asr_version = f"{engine.model_version}|{preprocessing.identity}"

            run = await _load_or_create_analysis_run(session, call_id, tenant_id)
            emotion_enabled = get_settings().voice_sentiment_enabled
            next_status = "emotion_queued" if emotion_enabled else "transcribed"
            call = (
                await session.execute(
                    select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            if call is not None:
                call.status = next_status
                call.error_code = None
                next_progress = progress.values_for_status(next_status)
                call.progress_pct = int(next_progress["progress_pct"])
                call.progress_detail = str(next_progress["progress_detail"])
                call.updated_at = datetime.now(UTC)
            await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="asr", status="succeeded"
            )
            next_kind = "emotion" if emotion_enabled else "llm"
            next_job = Job(
                tenant_id=tenant_id,
                call_id=call_id,
                kind=next_kind,
                status="queued",
                attempt=0,
            )
            session.add(next_job)
            await session.flush()
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind=next_kind,
                status="queued",
                progress_pct=int(next_progress["progress_pct"]),
                message=(
                    "تحلیل لحن صدا در صف پردازش قرار گرفت"
                    if emotion_enabled
                    else "تحلیل هوشمند در صف پردازش قرار گرفت"
                ),
                step_key=f"{next_job.id}:queued:0",
            )
            outbox_id = await outbox.stage_job(
                session,
                job_id=next_job.id,
                tenant_id=tenant_id,
                call_id=call_id,
                kind=next_kind,
                analysis_run_id=run.id,
            )
        asr_seconds_processed.inc(probe.duration_ms / 1000)
        try:
            await outbox.dispatch_one(outbox_id)
        except Exception:  # noqa: BLE001 - reconciler resumes the committed transcribed call
            logger.exception("immediate downstream dispatch failed; durable dispatcher will retry")
            return "transcribed_enqueue_pending"
        return "transcribed"
    except Exception as exc:  # noqa: BLE001 - retry policy owns the outcome
        code, detail, retryable = classify_failure(exc, kind="asr")
        retried = await pipeline.handle_failure(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="asr",
            error_code=code,
            error_detail=detail,
            retryable=retryable,
        )
        # handle_failure already requeued: re-raising would let ARQ add a second attempt (§6).
        return "retry_scheduled" if retried else "failed_terminal"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging("worker-asr", settings.log_level)
    start_metrics_server(settings)
    # VoiceSanj/Whisper credentials and model selection live in platform_settings.
    # Building either remote engine here would use env-only settings before a DB
    # session exists and can crash the worker before it ever consumes a job.
    ctx["engine"] = (
        None if settings.asr_engine in {"voicesanj", "whisper"} else build_engine(settings)
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await queue.get_queue().close()
    await dispose_engine()


async def pending_calls() -> list[UUID]:
    """Used by the reconciler cron (§6): rows stuck before transcription."""
    call_ids: list[UUID] = []
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            rows = await session.execute(
                select(Call.id).where(
                    Call.tenant_id == tenant_id,
                    Call.status == "stored",
                )
            )
            call_ids.extend(row[0] for row in rows)
    return call_ids


class WorkerSettings:
    functions = [transcribe_call]
    queue_name = queue.QUEUE_ASR
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    # VoiceSanj's own 30 minute poll deadline must fire before ARQ cancels the
    # coroutine, otherwise pipeline.handle_failure never records the outcome.
    job_timeout = 2100
    keep_result = 3600
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
