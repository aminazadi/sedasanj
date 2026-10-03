from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db import resolve_tenant_for_call, session_scope
from app.models import AnalysisRun, Call, Job, Transcript, TranscriptRevision, Utterance
from app.services import outbox, pipeline, processing_events, progress
from app.services.platform import (
    effective_extract_prompt,
    effective_models,
    resolve_provider_settings,
)
from app.services.provider_errors import ProviderError, classify_failure
from app.services.transcript_corrections import (
    CorrectionClient,
    activate_revision,
    advance_correction_model,
    current_correction_model,
    should_run_text_correction,
    source_segments,
    validate_result,
)

logger = logging.getLogger(__name__)


async def _stage_analysis(
    *, tenant_id: UUID, call_id: UUID, revision: TranscriptRevision
) -> UUID:
    async with session_scope(tenant_id) as session:
        call = await session.get(Call, call_id)
        run = (
            await session.execute(
                select(AnalysisRun)
                .where(
                    AnalysisRun.call_id == call_id,
                    AnalysisRun.tenant_id == tenant_id,
                    AnalysisRun.status.in_(("pending", "queued")),
                )
                .order_by(AnalysisRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if run is None or revision.trigger == "manual":
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
        else:
            run.status = "queued"
        job = Job(tenant_id=tenant_id, call_id=call_id, kind="llm", status="queued", attempt=0)
        session.add(job)
        if call is not None:
            call.status = "transcribed"
            values = progress.values_for_status("transcribed")
            call.progress_pct = int(values["progress_pct"])
            call.progress_detail = str(values["progress_detail"])
        await session.flush()
        await processing_events.record(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            status="queued",
            progress_pct=58,
            message="تحلیل متن تصحیح‌شده در صف پردازش قرار گرفت",
            step_key=f"{job.id}:queued:0",
        )
        return await outbox.stage_job(
            session,
            job_id=job.id,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            analysis_run_id=run.id,
            reanalysis=revision.trigger == "manual",
            previous_status=(revision.metrics or {}).get("previous_status")
            if revision.trigger == "manual"
            else None,
        )


async def _fail(
    tenant_id: UUID, call_id: UUID, revision_id: UUID, exc: Exception
) -> str:
    code, detail, retryable = classify_failure(exc, kind="llm")
    async with session_scope(tenant_id) as session:
        runtime = await resolve_provider_settings(session)
        revision = await session.get(TranscriptRevision, revision_id)
        is_manual = revision is not None and revision.trigger == "manual"
        if revision is not None:
            revision.error_code = code
            revision.error_detail = detail[:2000]
    retried = await pipeline.handle_failure(
        tenant_id=tenant_id,
        call_id=call_id,
        kind="correction",
        correction_run_id=revision_id,
        reanalysis=is_manual,
        error_code=code,
        error_detail=detail,
        retryable=retryable,
        max_attempts_override=runtime.correction_max_retries,
    )
    if not retried:
        async with session_scope(tenant_id) as session:
            revision = await session.get(TranscriptRevision, revision_id)
            if revision is not None:
                revision.status = "failed"
                revision.completed_at = datetime.now(UTC)
                if revision.trigger == "manual":
                    call = await session.get(Call, call_id)
                    if call is not None:
                        call.status = str(
                            (revision.metrics or {}).get("previous_status") or "complete"
                        )
                        call.error_code = None
    return "retry_scheduled" if retried else "failed_terminal"


async def start_transcript_correction(_: dict[str, Any], payload: dict[str, Any]) -> str:
    call_id = UUID(str(payload["call_id"]))
    revision_id = UUID(str(payload["correction_run_id"]))
    tenant_hint = UUID(str(payload["tenant_id"])) if payload.get("tenant_id") else None
    tenant_id = await resolve_tenant_for_call(call_id, tenant_hint)
    if tenant_id is None:
        return "missing"
    try:
        async with session_scope(tenant_id) as session:
            revision = await session.get(TranscriptRevision, revision_id)
            if revision is None or revision.status in {"succeeded", "failed"}:
                return "skipped"
            transcript = await session.get(Transcript, call_id)
            if transcript is None:
                raise RuntimeError("call has no transcript")
            utterances = list(
                (
                    await session.execute(
                        select(Utterance)
                        .where(Utterance.call_id == call_id, Utterance.tenant_id == tenant_id)
                        .order_by(Utterance.t_start_ms, Utterance.channel, Utterance.id)
                    )
                ).scalars()
            )
            segments = source_segments(utterances)
            if not segments:
                raise RuntimeError("call has no transcript segments")
            runtime = await resolve_provider_settings(session)
            revision.status = "running"
            revision.started_at = revision.started_at or datetime.now(UTC)
            await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="correction", status="running"
            )
            if not should_run_text_correction(revision.mode, revision.trigger):
                result = {
                    "model": transcript.asr_model,
                    "segments": [
                        {"id": row["id"], "corrected_text": row["text"], "uncertain": False}
                        for row in segments
                    ],
                    "uncertain_items": [],
                    "finish_reason": "stop",
                }
                validated, uncertain = validate_result(
                    segments, result, max_uncertain_ratio=runtime.correction_max_uncertain_ratio
                )
                await activate_revision(
                    session,
                    transcript=transcript,
                    revision=revision,
                    segments=validated,
                    uncertain_items=uncertain,
                    result=result,
                )
                await pipeline.mark_job(
                    session,
                    tenant_id=tenant_id,
                    call_id=call_id,
                    kind="correction",
                    status="succeeded",
                )
                dispatch_analysis = True
            elif revision.provider_task_id:
                dispatch_analysis = False
            else:
                client = CorrectionClient(runtime)
                try:
                    revision.provider_task_id = await client.submit(
                        revision,
                        segments,
                        runtime.correction_prompt,
                        model=current_correction_model(revision),
                    )
                finally:
                    await client.close()
                revision.provider_submitted_at = datetime.now(UTC)
                dispatch_analysis = False
        if dispatch_analysis:
            outbox_id = await _stage_analysis(
                tenant_id=tenant_id, call_id=call_id, revision=revision
            )
            await outbox.dispatch_one(outbox_id)
            return "succeeded"
        return await poll_transcript_correction({}, payload)
    except Exception as exc:  # noqa: BLE001
        return await _fail(tenant_id, call_id, revision_id, exc)


async def poll_transcript_correction(_: dict[str, Any], payload: dict[str, Any]) -> str:
    call_id = UUID(str(payload["call_id"]))
    revision_id = UUID(str(payload["correction_run_id"]))
    tenant_id = UUID(str(payload["tenant_id"]))
    try:
        async with session_scope(tenant_id) as session:
            revision = await session.get(TranscriptRevision, revision_id)
            transcript = await session.get(Transcript, call_id)
            if revision is None or transcript is None or not revision.provider_task_id:
                raise RuntimeError("correction provider task is missing")
            runtime = await resolve_provider_settings(session)
            if revision.started_at is not None and (
                datetime.now(UTC) - revision.started_at
            ).total_seconds() > runtime.correction_timeout_seconds:
                raise TimeoutError("correction processing deadline exceeded")
            utterances = list(
                (
                    await session.execute(
                        select(Utterance)
                        .where(Utterance.call_id == call_id, Utterance.tenant_id == tenant_id)
                        .order_by(Utterance.t_start_ms, Utterance.channel, Utterance.id)
                    )
                ).scalars()
            )
            segments = source_segments(utterances)
            client = CorrectionClient(runtime)
            try:
                state = await client.status(revision.provider_task_id)
                status = state.get("status")
                if status in {"queued", "running", "retrying"}:
                    job = (
                        await session.execute(
                            select(Job)
                            .where(Job.call_id == call_id, Job.kind == "correction")
                            .order_by(Job.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one()
                    outbox_id = await outbox.stage(
                        session,
                        tenant_id=tenant_id,
                        job_id=job.id,
                        queue_name="q:llm",
                        function_name="poll_transcript_correction",
                        payload={**payload, "tenant_id": str(tenant_id)},
                        available_at=datetime.now(UTC) + timedelta(seconds=3),
                    )
                    return_value = ("polling", outbox_id)
                elif status in {"succeeded", "partially_succeeded"}:
                    revision.status = "validating"
                    result = await client.result(revision.provider_task_id)
                    try:
                        validated, uncertain = validate_result(
                            segments,
                            result,
                            max_uncertain_ratio=runtime.correction_max_uncertain_ratio,
                        )
                    except ValueError as exc:
                        try:
                            model = advance_correction_model(revision, error=str(exc))
                        except Exception as exhausted:
                            raise ProviderError(
                                "correction_validation_failed",
                                "همه مدل‌های تصحیح متن خروجی نامعتبر ساختاری برگرداندند.",
                                retryable=False,
                            ) from exhausted
                        revision.status = "running"
                        revision.provider_task_id = await client.submit(
                            revision,
                            segments,
                            runtime.correction_prompt,
                            model=model,
                        )
                        revision.provider_submitted_at = datetime.now(UTC)
                        job = (
                            await session.execute(
                                select(Job)
                                .where(Job.call_id == call_id, Job.kind == "correction")
                                .order_by(Job.created_at.desc())
                                .limit(1)
                            )
                        ).scalar_one()
                        outbox_id = await outbox.stage(
                            session,
                            tenant_id=tenant_id,
                            job_id=job.id,
                            queue_name="q:llm",
                            function_name="poll_transcript_correction",
                            payload={**payload, "tenant_id": str(tenant_id)},
                            available_at=datetime.now(UTC) + timedelta(seconds=3),
                        )
                        return_value = ("polling", outbox_id)
                    else:
                        await activate_revision(
                            session,
                            transcript=transcript,
                            revision=revision,
                            segments=validated,
                            uncertain_items=uncertain,
                            result=result,
                        )
                        await pipeline.mark_job(
                            session,
                            tenant_id=tenant_id,
                            call_id=call_id,
                            kind="correction",
                            status="succeeded",
                        )
                        return_value = ("succeeded", None)
                elif status == "failed":
                    model = advance_correction_model(
                        revision,
                        error=str(state.get("error") or state.get("error_code") or status),
                    )
                    revision.provider_task_id = await client.submit(
                        revision,
                        segments,
                        runtime.correction_prompt,
                        model=model,
                    )
                    revision.provider_submitted_at = datetime.now(UTC)
                    job = (
                        await session.execute(
                            select(Job)
                            .where(Job.call_id == call_id, Job.kind == "correction")
                            .order_by(Job.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one()
                    outbox_id = await outbox.stage(
                        session,
                        tenant_id=tenant_id,
                        job_id=job.id,
                        queue_name="q:llm",
                        function_name="poll_transcript_correction",
                        payload={**payload, "tenant_id": str(tenant_id)},
                        available_at=datetime.now(UTC) + timedelta(seconds=3),
                    )
                    return_value = ("polling", outbox_id)
                else:
                    raise RuntimeError(
                        str(state.get("error") or state.get("error_code") or status)
                    )
            finally:
                await client.close()
        if return_value[0] == "polling":
            await outbox.dispatch_one(return_value[1])
            return "polling"
        outbox_id = await _stage_analysis(
            tenant_id=tenant_id, call_id=call_id, revision=revision
        )
        await outbox.dispatch_one(outbox_id)
        return "succeeded"
    except Exception as exc:  # noqa: BLE001
        return await _fail(tenant_id, call_id, revision_id, exc)
