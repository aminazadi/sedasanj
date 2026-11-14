from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import (
    dispose_engine,
    operational_tenant_ids,
    resolve_tenant_for_call,
    session_scope,
)
from app.logging import configure_logging, log_context
from app.metrics import (
    asr_call_attempts,
    asr_call_realtime_factor,
    asr_seconds_processed,
    start_metrics_server,
)
from app.models import (
    AnalysisRun,
    AsrTranscriptRevision,
    AudioObject,
    Call,
    Job,
    Tenant,
)
from app.services import analysis_runs, outbox, pipeline, processing_events, progress, queue
from app.services.asr_revisions import activate_new
from app.services.audio import (
    AudioPreprocessingConfig,
    ChannelLevelReport,
    preprocess_mono_audio,
    probe_wav_file,
    resample_to_16k,
    split_channels,
)
from app.services.call_speakers import render_turns, speaker_mode
from app.services.platform import resolve_provider_settings
from app.services.provider_errors import ASR_NO_SPEECH_DETAIL, ProviderError, classify_failure
from app.services.storage import get_storage
from app.services.transcript_corrections import create_revision
from worker_asr.engine import AsrEngine, AsrSegment, build_engine

logger = logging.getLogger(__name__)

TURN_MERGE_GAP_MS = 1_200


def _clean_segment_text(text: str) -> str:
    return " ".join(text.split()).strip()


def consolidate_segments(
    rows: list[tuple[int, AsrSegment]], *, merge_gap_ms: int = TURN_MERGE_GAP_MS
) -> list[tuple[int, AsrSegment]]:
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
            confidence=segment.confidence,
            metadata=segment.metadata,
        )
        if not merged:
            merged.append((channel, current))
            continue
        previous_channel, previous = merged[-1]
        if (
            previous_channel == channel
            and current.t_start_ms <= previous.t_end_ms + merge_gap_ms
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
                    confidence=(
                        min(
                            value
                            for value in (previous.confidence, current.confidence)
                            if value is not None
                        )
                        if previous.confidence is not None or current.confidence is not None
                        else None
                    ),
                    metadata={
                        "merged_segments": [previous.metadata or {}, current.metadata or {}],
                        "timestamp_source": (previous.metadata or {}).get(
                            "timestamp_source",
                            (current.metadata or {}).get("timestamp_source", "native"),
                        ),
                        **(
                            {"speaker": (previous.metadata or {}).get("speaker")}
                            if (previous.metadata or {}).get("speaker") is not None
                            else {}
                        ),
                    },
                ),
            )
            continue
        merged.append((channel, current))
    return merged


def build_full_text(
    rows: list[tuple[int, AsrSegment]], *, direction: str | None, mode: str
) -> str:
    return render_turns(
        ((channel, segment.t_start_ms, segment.text) for channel, segment in rows), direction, mode
    )


def call_asr_identity(
    rows: list[tuple[int, AsrSegment]],
    engine: AsrEngine,
    runtime: Settings,
    preprocessing: AudioPreprocessingConfig,
) -> tuple[str, str]:
    tracks = {
        (
            channel,
            str((segment.metadata or {}).get("asr_model") or engine.model_name),
            (segment.metadata or {}).get("timestamp_source") == "silero_vad",
        )
        for channel, segment in rows
    }
    models = sorted({model for _, model, _ in tracks})
    identities = {
        f"{model}|{preprocessing.identity}|segmenter:{'silero-vad' if silero else 'legacy'}"
        for _, model, silero in tracks
    }
    profile = f"|profile:{runtime.call_asr_profile}"
    threshold = runtime.call_asr_telephony_threshold
    if runtime.call_asr_profile == "telephony" and threshold is not None:
        profile += f"|threshold:{threshold}"
    if len(identities) == 1:
        suffix = profile if any(silero for _, _, silero in tracks) else ""
        return "+".join(models), next(iter(identities)) + suffix
    return "+".join(models), ";".join(
        f"ch{channel}:{model}|{preprocessing.identity}|segmenter:"
        f"{'silero-vad' if silero else 'legacy'}{profile if silero else ''}"
        for channel, model, silero in sorted(tracks)
    )


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
        await analysis_runs.ensure_snapshot(session, run)
        run.status = "queued"
        return run
    run = await analysis_runs.create(
        session, tenant_id=tenant_id, call_id=call_id, status="queued"
    )
    session.add(run)
    return run


def _log_channel_levels(*reports: ChannelLevelReport | None) -> None:
    """One line per channel: what the adaptive level matching measured and applied."""
    for channel, report in enumerate(reports):
        if report is None:
            continue
        logger.info(
            "asr channel level matched",
            extra={
                "extra_fields": {
                    "channel": channel,
                    "measured_lufs": report.measured_lufs,
                    "gain_db": report.gain_db,
                    "silent": report.silent,
                }
            },
        )


async def _transcribe_tracks(
    engine: AsrEngine,
    original: Path,
    scratch: Path,
    channels: int,
    preprocessing: AudioPreprocessingConfig | None = None,
    on_preprocessed: Callable[[], Awaitable[None]] | None = None,
) -> list[tuple[int, AsrSegment]]:
    preprocessing = preprocessing or AudioPreprocessingConfig()
    rows: list[tuple[int, AsrSegment]] = []
    if channels == 2:
        left, right = scratch / "left.wav", scratch / "right.wav"
        await split_channels(original, left, right)
        if preprocessing.enabled:
            left_ready = scratch / "left-preprocessed.wav"
            right_ready = scratch / "right-preprocessed.wav"
            left_report, right_report = await asyncio.gather(
                preprocess_mono_audio(left, left_ready, preprocessing),
                preprocess_mono_audio(right, right_ready, preprocessing),
            )
            _log_channel_levels(left_report, right_report)
            if on_preprocessed is not None:
                await on_preprocessed()
        else:
            left_ready, right_ready = left, right
        track_results = await asyncio.gather(
            engine.transcribe(left_ready),
            engine.transcribe(right_ready),
            return_exceptions=True,
        )
        channel_segments: list[list[AsrSegment]] = [[], []]
        for channel, result in enumerate(track_results):
            if isinstance(result, BaseException):
                code, _, _ = classify_failure(result, kind="asr")
                if (
                    code == "asr_no_speech"
                    or "no text for detected speech regions" in str(result).lower()
                ):
                    continue
                raise result
            channel_segments[channel] = result
        left_segments, right_segments = channel_segments
        rows.extend((0, segment) for segment in left_segments)
        rows.extend((1, segment) for segment in right_segments)
    else:
        mono = scratch / "mono16k.wav"
        if preprocessing.enabled:
            await preprocess_mono_audio(original, mono, preprocessing)
            if on_preprocessed is not None:
                await on_preprocessed()
        else:
            await resample_to_16k(original, mono)
        mono_segments = await engine.transcribe(mono, diarize=True)
        rows.extend(
            (
                int((segment.metadata or {}).get("speaker", 0)),
                segment,
            )
            for segment in mono_segments
        )
    recognized = [row for row in rows if row[1].text]
    if not recognized:
        raise ProviderError("asr_no_speech", ASR_NO_SPEECH_DETAIL, retryable=False)
    return recognized


async def _engine_for_job(
    ctx: dict[str, Any],
    session: AsyncSession,
    provider_override: str | None = None,
    model_override: str | None = None,
    tenant_id: UUID | None = None,
) -> tuple[AsrEngine, AudioPreprocessingConfig, Settings]:
    """Remote engines rebuild per job so admin model/API-key changes apply immediately."""
    tenant = await session.get(Tenant, tenant_id) if tenant_id is not None else None
    runtime = await resolve_provider_settings(
        session, capability="asr", provider_override=provider_override, call_tenant=tenant
    )
    mode = runtime.call_asr_mode
    if model_override and mode == "legacy":
        runtime = runtime.model_copy(
            update={
                "asr_model_name": model_override,
                "voicesanj_asr_model": model_override,
                "whisper_model": model_override,
            }
        )
    if runtime.asr_engine in {"voicesanj", "whisper"}:
        engine = build_engine(runtime)
    else:
        local_engine = ctx.get("engine")
        if not isinstance(local_engine, AsrEngine):
            raise RuntimeError("local ASR engine was not initialized")
        engine = local_engine
        engine.model_name = runtime.asr_model_name
    preprocessing = AudioPreprocessingConfig(
        enabled=runtime.audio_preprocessing_enabled and mode == "legacy",
        denoiser_model=runtime.audio_denoiser_model,
        enhancement_model=runtime.audio_enhancement_model,
        target_loudness_lufs=runtime.audio_target_loudness_lufs,
        max_gain_db=runtime.audio_max_gain_db,
    )
    preprocessing.validate()
    return engine, preprocessing, runtime


async def transcribe_call(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    call_id = UUID(str(payload["call_id"]))
    recovery = bool(payload.get("recovery", False))
    retranscription = bool(payload.get("retranscription", False))
    previous_status = str(payload.get("previous_status") or "complete")
    asr_revision_id = (
        UUID(str(payload["asr_revision_id"])) if payload.get("asr_revision_id") else None
    )
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
        revision_snapshot = (
            await session.get(AsrTranscriptRevision, asr_revision_id)
            if asr_revision_id is not None
            else None
        )
        latest_job = (
            await session.execute(
                select(Job)
                .where(Job.tenant_id == tenant_id, Job.call_id == call_id, Job.kind == "asr")
                .order_by(Job.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        provider_snapshot = (
            revision_snapshot.ai_provider
            if revision_snapshot is not None
            else latest_job.ai_provider
            if latest_job is not None
            else "aiservice"
        )
        model_snapshot = (
            revision_snapshot.asr_model
            if revision_snapshot is not None and revision_snapshot.asr_model
            else latest_job.ai_model
            if latest_job is not None
            else None
        )
    log_context(
        tenant_id=str(tenant_id),
        call_id=str(call_id),
        request_id=str(payload.get("request_id") or call_id),
    )

    deferred_outbox_id: UUID | None = None
    asr_running_step_key: str | None = None
    async with session_scope(tenant_id) as session:
        slot_free = await pipeline.concurrency_slot_free(
            session, tenant_id, concurrency_limit, kind="asr"
        )
        if asr_revision_id is not None:
            revision = await session.get(AsrTranscriptRevision, asr_revision_id)
            if (
                revision is None
                or revision.call_id != call_id
                or revision.tenant_id != tenant_id
                or revision.status not in {"queued", "running"}
            ):
                return "skipped"
            job_status = await session.scalar(
                select(Job.status)
                .where(Job.tenant_id == tenant_id, Job.call_id == call_id, Job.kind == "asr")
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(1)
            )
            if job_status not in {"queued", "failed_retryable"}:
                return "skipped"
        if not slot_free:
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
                asr_revision_id=asr_revision_id,
                retranscription=retranscription,
                previous_status=previous_status,
                available_at=datetime.now(UTC) + timedelta(seconds=30),
            )
        else:
            claimed = await pipeline.claim_call(
                session,
                call_id,
                tenant_id=tenant_id,
                expected=(previous_status, "failed_retryable", "transcribing")
                if retranscription
                else ("stored", "failed_retryable", "transcribing")
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
            direction = claimed.direction
            asr_job = await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="asr", status="running"
            )
            if asr_revision_id is not None:
                asr_revision = await session.get(AsrTranscriptRevision, asr_revision_id)
                if asr_revision is not None:
                    asr_revision.status = "running"
            asr_running_step_key = f"{asr_job.id}:running:{asr_job.attempt}"

    if deferred_outbox_id is not None:
        await outbox.dispatch_one(deferred_outbox_id)
        return "deferred"

    mode = "legacy"
    try:
        async with session_scope(None, staff=True) as session:
            engine, preprocessing, runtime = await _engine_for_job(
                ctx, session, provider_snapshot, model_snapshot, tenant_id
            )
        mode = runtime.call_asr_mode
        if preprocessing.enabled:
            async with session_scope(tenant_id) as session:
                # This is deliberately a separate, settled event.  Otherwise the
                # generic ASR "running" row makes the UI look as if denoising
                # started after transcription.
                await processing_events.record(
                    session,
                    call_id=call_id,
                    tenant_id=tenant_id,
                    kind="asr",
                    status="running",
                    progress_pct=20,
                    message="حذف نویز و بهبود کیفیت صوت، پیش از تبدیل گفتار، شروع شد",
                    step_key=asr_running_step_key,
                )
        with tempfile.TemporaryDirectory(prefix="cbi-asr-") as tmp:
            scratch = Path(tmp)
            original = scratch / "original.wav"
            with original.open("wb") as audio_file:
                async for chunk in get_storage().iter_chunks(object_key):
                    audio_file.write(chunk)
            probe = await probe_wav_file(original)
            async def mark_audio_ready() -> None:
                async with session_scope(tenant_id) as session:
                    await processing_events.record(
                        session,
                        call_id=call_id,
                        tenant_id=tenant_id,
                        kind="asr",
                        level="success",
                        status="succeeded",
                        progress_pct=20,
                        message="حذف نویز و بهبود کیفیت صوت، پیش از تبدیل گفتار، انجام شد",
                        step_key=asr_running_step_key,
                    )
                    await progress.report(
                        session,
                        call_id=call_id,
                        tenant_id=tenant_id,
                        pct=25,
                        detail="صوت آماده است؛ در حال تبدیل گفتار به متن",
                        kind="asr",
                    )

            if not preprocessing.enabled:
                async with session_scope(tenant_id) as session:
                    await progress.report(
                        session,
                        call_id=call_id,
                        tenant_id=tenant_id,
                        pct=25,
                        detail="صوت آماده است؛ در حال تبدیل گفتار به متن",
                        kind="asr",
                    )
            started = monotonic()
            tracks = await _transcribe_tracks(
                engine,
                original,
                scratch,
                audio_channels,
                preprocessing,
                on_preprocessed=mark_audio_ready if preprocessing.enabled else None,
            )
            if probe.duration_ms > 0:
                asr_call_realtime_factor.labels(mode).observe(
                    (monotonic() - started) / (probe.duration_ms / 1000)
                )
            asr_model, asr_identity = call_asr_identity(tracks, engine, runtime, preprocessing)
            logger.info(
                "call ASR completed",
                extra={"extra_fields": {"mode": mode, "asr_identity": asr_identity}},
            )
            rows = consolidate_segments(tracks, merge_gap_ms=runtime.turn_merge_gap_ms)

        diarized = any((segment.metadata or {}).get("speaker") is not None for _, segment in rows)
        layout = speaker_mode(audio_channels, diarized=diarized)
        full_text = build_full_text(rows, direction=direction, mode=layout)

        async with session_scope(tenant_id) as session:
            asr_revision = (
                await session.get(AsrTranscriptRevision, asr_revision_id)
                if asr_revision_id is not None
                else None
            )
            transcript_row, _ = await activate_new(
                session,
                call_id=call_id,
                tenant_id=tenant_id,
                rows=rows,
                full_text=full_text,
                asr_model=asr_model,
                asr_identity=asr_identity,
                asr_version=f"{engine.model_version}|{preprocessing.identity}",
                audio_channels=audio_channels,
                ai_provider=runtime.active_ai_provider,
                revision=asr_revision,
            )

            run = await _load_or_create_analysis_run(session, call_id, tenant_id)
            if retranscription:
                run.result = {
                    **(run.result or {}),
                    "_reanalysis": True,
                    "_previous_status": previous_status,
                }
            emotion_enabled = get_settings().voice_sentiment_enabled
            correction_runtime = await resolve_provider_settings(session, capability="correction")
            correction_enabled = correction_runtime.correction_enabled
            next_status = (
                "emotion_queued"
                if emotion_enabled
                else "correcting"
                if correction_enabled
                else "transcribed"
            )
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
            next_kind = (
                "emotion"
                if emotion_enabled
                else "correction"
                if correction_enabled
                else "llm"
            )
            if next_kind == "correction":
                assert call is not None
                _revision, _job, outbox_id, _created = await create_revision(
                    session,
                    call=call,
                    transcript=transcript_row,
                    runtime=correction_runtime,
                    trigger="automatic",
                    reanalysis_previous_status=previous_status if retranscription else None,
                )
                next_job = None
            else:
                next_job = Job(
                    tenant_id=tenant_id,
                    call_id=call_id,
                    kind=next_kind,
                    status="queued",
                    attempt=0,
                )
                session.add(next_job)
                await session.flush()
            if next_job is not None:
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
                    reanalysis=retranscription,
                    previous_status=previous_status if retranscription else None,
                )
        asr_call_attempts.labels(mode, "succeeded").inc()
        asr_seconds_processed.inc(probe.duration_ms / 1000)
        try:
            await outbox.dispatch_one(outbox_id)
        except Exception:  # noqa: BLE001 - reconciler resumes the committed transcribed call
            logger.exception("immediate downstream dispatch failed; durable dispatcher will retry")
            return "transcribed_enqueue_pending"
        return "transcribed"
    except Exception as exc:  # noqa: BLE001 - retry policy owns the outcome
        code, detail, retryable = classify_failure(exc, kind="asr")
        asr_call_attempts.labels(mode, code).inc()
        retried = await pipeline.handle_failure(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="asr",
            error_code=code,
            error_detail=detail,
            retryable=retryable,
            reanalysis=retranscription,
            previous_status=previous_status,
            asr_revision_id=asr_revision_id,
            retranscription=retranscription,
        )
        if asr_revision_id is not None:
            async with session_scope(tenant_id) as session:
                revision = await session.get(AsrTranscriptRevision, asr_revision_id)
                if revision is not None:
                    revision.status = "running" if retried else "failed"
                    revision.error_code = code
                    revision.error_detail = detail[:2000]
                    if not retried:
                        revision.completed_at = datetime.now(UTC)
                        call = await session.get(Call, call_id)
                        if call is not None:
                            prior = revision.metrics or {}
                            call.status = previous_status
                            call.error_code = prior.get("previous_error_code")
                            if isinstance(prior.get("previous_progress_pct"), int):
                                call.progress_pct = prior["previous_progress_pct"]
                                call.progress_detail = prior.get("previous_progress_detail")
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
    job_serializer = queue.job_serializer
    job_deserializer = queue.job_deserializer
    functions = [transcribe_call]
    queue_name = queue.QUEUE_ASR
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = get_settings().asr_worker_max_jobs
    # VoiceSanj's own 30 minute poll deadline must fire before ARQ cancels the
    # coroutine, otherwise pipeline.handle_failure never records the outcome.
    job_timeout = 2100
    keep_result = 3600
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
