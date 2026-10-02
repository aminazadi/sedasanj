from __future__ import annotations

import asyncio
import logging
import tempfile
import wave
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import get_settings
from app.db import dispose_engine, resolve_tenant_for_call, session_scope
from app.logging import configure_logging, log_context
from app.metrics import start_metrics_server
from app.models import AudioObject, Call, CallInsight, Job, Transcript, Utterance
from app.schemas import DualPartySentiment, PartySentiment, SentimentPoint, SentimentWindow
from app.sentiment import merge_sentiment_profile
from app.services import outbox, pipeline, processing_events, progress, queue
from app.services.audio import resample_to_16k, split_channels
from app.services.platform import resolve_provider_settings
from app.services.provider_errors import classify_failure
from app.services.storage import get_storage
from app.services.transcript_corrections import create_revision
from worker_emotion.engine import TARGET_LABELS, Emotion2VecEngine, EmotionPrediction

logger = logging.getLogger(__name__)
WINDOW_MERGE_GAP_MS = 500


@dataclass(frozen=True, slots=True)
class AudioWindow:
    channel: int
    t_start_ms: int
    t_end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.t_end_ms - self.t_start_ms


def _evenly_limit(items: list[AudioWindow], limit: int) -> list[AudioWindow]:
    if len(items) <= limit:
        return items
    if limit == 1:
        return [items[0]]
    indexes = [round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)]
    return [items[index] for index in indexes]


def build_audio_windows(
    utterances: Iterable[Utterance],
    *,
    duration_ms: int,
    max_window_ms: int,
    min_window_ms: int,
    max_windows: int,
) -> list[AudioWindow]:
    by_channel: dict[int, list[tuple[int, int]]] = {0: [], 1: []}
    for utterance in utterances:
        start = max(0, min(int(utterance.t_start_ms), duration_ms))
        end = max(start, min(int(utterance.t_end_ms), duration_ms))
        if end > start and utterance.channel in by_channel:
            by_channel[utterance.channel].append((start, end))

    windows: list[AudioWindow] = []
    for channel, intervals in by_channel.items():
        merged: list[tuple[int, int]] = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1] + WINDOW_MERGE_GAP_MS:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        channel_windows: list[AudioWindow] = []
        for start, end in merged:
            cursor = start
            while cursor < end:
                piece_end = min(cursor + max_window_ms, end)
                piece_start = cursor
                if piece_end - piece_start < min_window_ms:
                    piece_start = max(0, piece_end - min_window_ms)
                    piece_end = min(duration_ms, piece_start + min_window_ms)
                if piece_end > piece_start:
                    candidate = AudioWindow(channel, piece_start, piece_end)
                    if not channel_windows or candidate != channel_windows[-1]:
                        channel_windows.append(candidate)
                cursor += max_window_ms
        windows.extend(_evenly_limit(channel_windows, max_windows))
    return sorted(windows, key=lambda item: (item.channel, item.t_start_ms, item.t_end_ms))


def write_wav_window(source: Path, target: Path, window: AudioWindow) -> None:
    with wave.open(str(source), "rb") as reader:
        if reader.getnchannels() != 1:
            raise RuntimeError("voice sentiment expects a mono track")
        frame_rate = reader.getframerate()
        start_frame = min(reader.getnframes(), round(window.t_start_ms * frame_rate / 1000))
        end_frame = min(reader.getnframes(), round(window.t_end_ms * frame_rate / 1000))
        reader.setpos(start_frame)
        frames = reader.readframes(max(0, end_frame - start_frame))
        params = reader.getparams()
    if not frames:
        raise RuntimeError("voice sentiment window contains no audio frames")
    with wave.open(str(target), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)


def _aggregate_predictions(
    rows: list[tuple[AudioWindow, EmotionPrediction]],
) -> SentimentPoint:
    totals: dict[str, float] = dict.fromkeys(TARGET_LABELS, 0.0)
    total_weight = 0.0
    for window, prediction in rows:
        weight = max(float(window.duration_ms), 1.0)
        total_weight += weight
        for label, probability in prediction.probabilities.items():
            totals[label] += probability * weight
    if total_weight <= 0:
        raise RuntimeError("cannot aggregate empty voice sentiment predictions")
    probabilities = {label: score / total_weight for label, score in totals.items()}
    label = max(TARGET_LABELS, key=lambda item: probabilities[item])
    return SentimentPoint(label=label, score=round(probabilities[label], 6))


def build_party_sentiment(
    rows: list[tuple[AudioWindow, EmotionPrediction]],
) -> PartySentiment:
    if not rows:
        raise RuntimeError("cannot build voice sentiment without windows")
    ordered = sorted(rows, key=lambda item: item[0].t_start_ms)
    edge_count = max(1, min(3, round(len(ordered) * 0.2)))
    timeline = [
        SentimentWindow(
            t_start_ms=window.t_start_ms,
            t_end_ms=window.t_end_ms,
            label=prediction.label,
            score=prediction.score,
            valence=prediction.valence,
        )
        for window, prediction in ordered
    ]
    return PartySentiment(
        start=_aggregate_predictions(ordered[:edge_count]),
        end=_aggregate_predictions(ordered[-edge_count:]),
        overall=_aggregate_predictions(ordered),
        timeline=timeline,
    )


def build_voice_profile(
    windows: list[AudioWindow], predictions: list[EmotionPrediction]
) -> DualPartySentiment | None:
    if len(windows) != len(predictions):
        raise RuntimeError("voice sentiment windows and predictions are not aligned")
    grouped: dict[int, list[tuple[AudioWindow, EmotionPrediction]]] = {0: [], 1: []}
    for window, prediction in zip(windows, predictions, strict=True):
        grouped[window.channel].append((window, prediction))
    if not grouped[0]:
        return None
    return DualPartySentiment(
        caller=build_party_sentiment(grouped[0]),
        agent=build_party_sentiment(grouped[1]) if grouped[1] else None,
    )


async def _prepare_tracks(original: Path, scratch: Path, channels: int) -> dict[int, Path]:
    if channels == 2:
        left = scratch / "caller.wav"
        right = scratch / "agent.wav"
        await split_channels(original, left, right)
        caller_16k = scratch / "caller-16k.wav"
        agent_16k = scratch / "agent-16k.wav"
        await asyncio.gather(
            resample_to_16k(left, caller_16k),
            resample_to_16k(right, agent_16k),
        )
        return {0: caller_16k, 1: agent_16k}
    caller_16k = scratch / "caller-16k.wav"
    await resample_to_16k(original, caller_16k)
    return {0: caller_16k}


async def _stage_llm(
    *, tenant_id: UUID, call_id: UUID, analysis_run_id: UUID, message: str
) -> UUID | None:
    async with session_scope(tenant_id) as session:
        runtime = await resolve_provider_settings(session)
        call = await session.get(Call, call_id)
        if runtime.correction_enabled and call is not None:
            transcript = await session.get(Transcript, call_id)
            if transcript is None:
                raise RuntimeError("call has no transcript")
            _revision, _job, outbox_id, created = await create_revision(
                session,
                call=call,
                transcript=transcript,
                runtime=runtime,
                trigger="automatic",
            )
            return outbox_id if created else None
        active = (
            await session.execute(
                select(Job)
                .where(
                    Job.tenant_id == tenant_id,
                    Job.call_id == call_id,
                    Job.kind == "llm",
                    Job.status.in_(("queued", "running")),
                )
                .order_by(Job.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if call is not None:
            call.status = "transcribed"
            call.error_code = None
            values = progress.values_for_status("transcribed")
            call.progress_pct = int(values["progress_pct"])
            call.progress_detail = str(values["progress_detail"])
            call.updated_at = datetime.now(UTC)
        if active is not None:
            return None
        job = Job(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            status="queued",
            attempt=0,
        )
        session.add(job)
        await session.flush()
        await processing_events.record(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            status="queued",
            progress_pct=55,
            message=message,
            step_key=f"{job.id}:queued:0",
        )
        return await outbox.stage_job(
            session,
            job_id=job.id,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            analysis_run_id=analysis_run_id,
        )


async def _run_inference(
    engine: Emotion2VecEngine,
    *,
    original: Path,
    scratch: Path,
    channels: int,
    windows: list[AudioWindow],
) -> list[EmotionPrediction]:
    tracks = await _prepare_tracks(original, scratch, channels)
    paths: list[Path] = []
    for index, window in enumerate(windows):
        source = tracks.get(window.channel)
        if source is None:
            raise RuntimeError(f"audio channel {window.channel} is unavailable")
        target = scratch / f"emotion-{index:04d}.wav"
        write_wav_window(source, target, window)
        paths.append(target)
    return await engine.analyze_many(paths)


async def analyze_voice_sentiment(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    call_id = UUID(str(payload["call_id"]))
    analysis_run_id = UUID(str(payload["analysis_run_id"]))
    recovery = bool(payload.get("recovery", False))
    settings = get_settings()

    tenant_hint = UUID(str(payload["tenant_id"])) if payload.get("tenant_id") else None
    tenant_id = await resolve_tenant_for_call(call_id, tenant_hint)
    if tenant_id is None:
        return "missing"
    async with session_scope(tenant_id) as session:
        call = await session.get(Call, call_id)
        if call is None:
            return "missing"
    log_context(tenant_id=str(tenant_id), call_id=str(call_id))

    async with session_scope(tenant_id) as session:
        job = await pipeline.lock_job_for_claim(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="emotion",
            expected=("queued", "failed_retryable", "running")
            if recovery
            else ("queued", "failed_retryable"),
        )
        if job is None:
            return "skipped"
        call = await session.get(Call, call_id)
        if call is None or call.audio_id is None:
            raise RuntimeError("call has no audio object")
        audio = await session.get(AudioObject, call.audio_id)
        if audio is None or audio.deleted_at is not None:
            raise RuntimeError("call audio is unavailable")
        utterances = list(
            (
                await session.execute(
                    select(Utterance)
                    .where(Utterance.call_id == call_id, Utterance.tenant_id == tenant_id)
                    .order_by(Utterance.channel, Utterance.t_start_ms)
                )
            ).scalars()
        )
        object_key = audio.object_key
        channels = audio.channels
        duration_ms = audio.duration_ms
        await pipeline.mark_job(
            session, tenant_id=tenant_id, call_id=call_id, kind="emotion", status="running"
        )
        call.status = "emotion_analyzing"
        call.error_code = None
        values = progress.values_for_status("emotion_analyzing")
        call.progress_pct = int(values["progress_pct"])
        call.progress_detail = str(values["progress_detail"])
        call.updated_at = datetime.now(UTC)

    try:
        windows = build_audio_windows(
            utterances,
            duration_ms=duration_ms,
            max_window_ms=round(settings.voice_sentiment_window_seconds * 1000),
            min_window_ms=round(settings.voice_sentiment_min_seconds * 1000),
            max_windows=settings.voice_sentiment_max_windows,
        )
        if not windows:
            raise RuntimeError("transcript contains no usable voice sentiment windows")
        engine = ctx.get("engine")
        if not isinstance(engine, Emotion2VecEngine):
            raise RuntimeError("emotion2vec engine was not initialized")

        with tempfile.TemporaryDirectory(prefix="cbi-emotion-") as tmp:
            scratch = Path(tmp)
            original = scratch / "original.wav"
            original.write_bytes(await get_storage().get(object_key))
            async with asyncio.timeout(settings.voice_sentiment_timeout_seconds):
                predictions = await _run_inference(
                    engine,
                    original=original,
                    scratch=scratch,
                    channels=channels,
                    windows=windows,
                )
        voice = build_voice_profile(windows, predictions)

        async with session_scope(tenant_id) as session:
            await pipeline.mark_job(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="emotion",
                status="succeeded",
            )
            if voice is not None:
                insight = await session.get(CallInsight, call_id)
                if insight is None:
                    insight = CallInsight(call_id=call_id, tenant_id=tenant_id)
                    session.add(insight)
                insight.sentiment_profile = merge_sentiment_profile(
                    insight.sentiment_profile,
                    voice=voice.model_dump(mode="json"),
                    voice_model=(
                        f"{settings.voice_sentiment_model}@"
                        f"{settings.voice_sentiment_model_revision}"
                    ),
                )

        outbox_id = await _stage_llm(
            tenant_id=tenant_id,
            call_id=call_id,
            analysis_run_id=analysis_run_id,
            message="تحلیل هوشمند متن در صف پردازش قرار گرفت",
        )
        if outbox_id is not None:
            try:
                await outbox.dispatch_one(outbox_id)
            except Exception:
                logger.exception("immediate LLM dispatch failed; durable dispatcher will retry")
                return "emotion_analyzed_enqueue_pending"
        return "emotion_analyzed"
    except Exception as exc:  # noqa: BLE001 - the retry policy owns the outcome
        code, detail, retryable = classify_failure(exc, kind="emotion")
        retried = await pipeline.handle_failure(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="emotion",
            error_code=code,
            error_detail=detail,
            analysis_run_id=analysis_run_id,
            retryable=retryable,
        )
        if retried:
            return "retry_scheduled"

        async with session_scope(tenant_id) as session:
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="emotion",
                level="warning",
                status="degraded",
                message="تحلیل لحن در دسترس نبود؛ پردازش با تحلیل متن ادامه پیدا کرد",
                error_code=code,
                error_detail=detail,
                step_key=f"emotion-fallback:{analysis_run_id}",
            )
        outbox_id = await _stage_llm(
            tenant_id=tenant_id,
            call_id=call_id,
            analysis_run_id=analysis_run_id,
            message="پردازش بدون تحلیل لحن و با تحلیل متن ادامه پیدا کرد",
        )
        if outbox_id is not None:
            try:
                await outbox.dispatch_one(outbox_id)
            except Exception:
                logger.exception("fallback LLM dispatch failed; durable dispatcher will retry")
                return "degraded_enqueue_pending"
        return "degraded"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging("worker-emotion", settings.log_level)
    start_metrics_server(settings)
    ctx["engine"] = Emotion2VecEngine(
        model=settings.voice_sentiment_model,
        revision=settings.voice_sentiment_model_revision,
        hub=settings.voice_sentiment_hub,
        device=settings.voice_sentiment_device,
        cpu_threads=settings.voice_sentiment_cpu_threads,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await queue.get_queue().close()
    await dispose_engine()


class WorkerSettings:
    functions = [analyze_voice_sentiment]
    queue_name = queue.QUEUE_EMOTION
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = get_settings().max_concurrent_emotion_jobs
    job_timeout = int(get_settings().voice_sentiment_timeout_seconds) + 300
    keep_result = 3600
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
