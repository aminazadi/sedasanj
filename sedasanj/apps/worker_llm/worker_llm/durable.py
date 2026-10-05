from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from app.db import session_scope
from app.metrics import llm_provider_wait_seconds, llm_submit_seconds
from app.models import AnalysisRun, AnalysisStep, Call, CallInsight, Job
from app.schemas import ExtractionResult
from app.sentiment import merge_sentiment_profile
from app.services import (
    billing,
    follow_up_tasks,
    knowledge,
    outbox,
    pipeline,
    processing_events,
    progress,
    queue,
    sales_insights,
)
from app.services.platform import resolve_provider_settings
from app.services.provider_errors import ProviderError, classify_failure
from worker_llm.chunking import plan_chunks
from worker_llm.client import VoiceSanjChatClient, extract_json, load_run_prompt
from worker_llm.prompts import build_repair_request

logger = logging.getLogger(__name__)

MAP_INSTRUCTION = (
    "این بخشی از یک مکالمه تلفنی فارسی است. آن را در حداکثر ۵ جمله فارسی خلاصه کن "
    "و نکات کلیدی، مبالغ، تاریخ‌ها و کارهای قابل پیگیری را حفظ کن. فقط متن خلاصه را بنویس."
)
REDUCE_HEADER = "خلاصه بخش‌های مکالمه (به ترتیب):"


def _step_key(run_id: UUID, kind: str, ordinal: int, input_text: str) -> tuple[str, str]:
    digest = hashlib.sha256(input_text.encode()).hexdigest()
    identity = hashlib.sha256(f"{run_id}:{kind}:{ordinal}:{digest}".encode()).hexdigest()
    return digest, f"cbi-analysis-{identity}"


async def _create_step(
    session: Any,
    *,
    run: AnalysisRun,
    kind: str,
    ordinal: int,
    system_prompt: str,
    input_text: str,
) -> tuple[AnalysisStep, UUID]:
    digest, key = _step_key(run.id, kind, ordinal, input_text)
    existing = (
        await session.execute(
            select(AnalysisStep).where(
                AnalysisStep.analysis_run_id == run.id,
                AnalysisStep.kind == kind,
                AnalysisStep.ordinal == ordinal,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        step = existing
        step.status = "queued"
        step.error_code = None
        step.error_detail = None
    else:
        step = AnalysisStep(
            analysis_run_id=run.id,
            tenant_id=run.tenant_id,
            kind=kind,
            ordinal=ordinal,
            status="queued",
            system_prompt=system_prompt,
            input_text=input_text,
            input_sha256=digest,
            idempotency_key=key,
        )
        session.add(step)
    await session.flush()
    outbox_id = await outbox.stage(
        session,
        tenant_id=run.tenant_id,
        queue_name=queue.QUEUE_LLM,
        function_name="submit_analysis_step",
        payload={"tenant_id": str(run.tenant_id), "step_id": str(step.id)},
    )
    return step, outbox_id


async def _stage_analysis_plan(session: Any, run: AnalysisRun, text: str) -> list[UUID]:
    plan = plan_chunks(text)
    workflow = dict(run.result or {})
    workflow["_strategy"] = plan.strategy
    workflow["_extra_reduce"] = plan.extra_reduce
    run.result = workflow
    outbox_ids: list[UUID] = []
    if plan.strategy == "single":
        _, outbox_id = await _create_step(
            session,
            run=run,
            kind="extract",
            ordinal=0,
            system_prompt=load_run_prompt(run.prompt_version, run.system_prompt),
            input_text=plan.chunks[0],
        )
        outbox_ids.append(outbox_id)
        return outbox_ids
    for ordinal, chunk in enumerate(plan.chunks):
        _, outbox_id = await _create_step(
            session,
            run=run,
            kind="map",
            ordinal=ordinal,
            system_prompt=MAP_INSTRUCTION,
            input_text=chunk,
        )
        outbox_ids.append(outbox_id)
    return outbox_ids


async def start_analysis(
    *,
    tenant_id: UUID,
    call_id: UUID,
    run_id: UUID,
    text: str,
    duration_ms: int,
    reanalysis: bool,
    previous_status: str | None,
) -> str:
    outbox_ids: list[UUID] = []
    async with session_scope(tenant_id) as session:
        run = await session.get(AnalysisRun, run_id)
        if run is None or run.tenant_id != tenant_id:
            raise RuntimeError("analysis run disappeared before preparation")
        run.result = {
            "_workflow": True,
            "_duration_ms": duration_ms,
            "_reanalysis": reanalysis,
            "_previous_status": previous_status,
        }
        outbox_ids.extend(await _stage_analysis_plan(session, run, text))
        await progress.report(
            session,
            call_id=call_id,
            tenant_id=tenant_id,
            pct=68,
            detail="متن آماده شد؛ درخواست‌های تحلیل در حال ارسال هستند",
            kind="llm",
        )
    for outbox_id in outbox_ids:
        await _best_effort_dispatch(outbox_id)
    return "analysis_steps_queued"


async def submit_analysis_step(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    step_id = UUID(str(payload["step_id"]))
    tenant_id = UUID(str(payload["tenant_id"]))
    async with session_scope(tenant_id) as session:
        step = (
            await session.execute(
                select(AnalysisStep).where(AnalysisStep.id == step_id).with_for_update()
            )
        ).scalar_one_or_none()
        if step is None:
            return "missing"
        if step.status in {"submitted", "polling", "succeeded"}:
            return "already_submitted"
        run = await session.get(AnalysisRun, step.analysis_run_id)
        if run is None:
            return "missing_run"
        call_id = run.call_id
        system_prompt, input_text = step.system_prompt, step.input_text
        key, model = step.idempotency_key, run.llm_model

    try:
        async with session_scope(None, staff=True) as session:
            runtime = await resolve_provider_settings(
                session, capability="analysis", provider_override=run.ai_provider
            )
        client = VoiceSanjChatClient(runtime, request_namespace=str(step.analysis_run_id))
        try:
            provider_task_id = await client.submit(
                system_prompt,
                input_text,
                model=model,
                idempotency_key=key,
            )
        finally:
            await client.close()
        now = datetime.now(UTC)
        async with session_scope(tenant_id) as session:
            step = (
                await session.execute(
                    select(AnalysisStep).where(AnalysisStep.id == step_id).with_for_update()
                )
            ).scalar_one_or_none()
            if step is None or step.status == "succeeded":
                return "already_completed"
            step.provider_task_id = provider_task_id
            step.status = "submitted"
            step.submitted_at = now
            job = await _latest_job(session, tenant_id, call_id)
            if job is not None and job.provider_submitted_at is None:
                job.provider_submitted_at = now
                llm_submit_seconds.observe(max((now - job.queued_at).total_seconds(), 0.0))
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="llm",
                status="running",
                progress_pct=72,
                message="درخواست به سرویس هوش مصنوعی ارسال شد",
                step_key=f"{step.id}:submitted",
            )
            poll_id = await _stage_poll(session, step, runtime.llm_poll_interval_seconds)
        await _best_effort_dispatch(poll_id)
        return "submitted"
    except Exception as exc:
        return await _retry_or_fail_step(tenant_id, step_id, exc, phase="submit")


async def poll_analysis_step(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    step_id = UUID(str(payload["step_id"]))
    tenant_id = UUID(str(payload["tenant_id"]))
    async with session_scope(tenant_id) as session:
        step = await session.get(AnalysisStep, step_id)
        if step is None:
            return "missing"
        if step.status == "succeeded":
            return "already_completed"
        if not step.provider_task_id:
            return "not_submitted"
        run = await session.get(AnalysisRun, step.analysis_run_id)
        if run is None:
            return "missing_run"
        call_id = run.call_id
        provider_task_id = step.provider_task_id
        submitted_at = step.submitted_at

    try:
        async with session_scope(None, staff=True) as session:
            runtime = await resolve_provider_settings(
                session, capability="analysis", provider_override=run.ai_provider
            )
        if submitted_at and datetime.now(UTC) - submitted_at > timedelta(
            seconds=runtime.analysis_timeout_seconds
        ):
            raise ProviderError(
                "llm_provider_timeout", "مهلت دریافت نتیجه تحلیل تمام شد.", retryable=True
            )
        chat_client = VoiceSanjChatClient(runtime, request_namespace=str(step.analysis_run_id))
        try:
            status = await chat_client.task_status(provider_task_id)
            state = status.get("status")
            if state in {"queued", "running", "retrying"}:
                async with session_scope(tenant_id) as session:
                    current = (
                        await session.execute(
                            select(AnalysisStep).where(AnalysisStep.id == step_id).with_for_update()
                        )
                    ).scalar_one_or_none()
                    if current is None or current.status == "succeeded":
                        return "already_completed"
                    current.status = "polling"
                    poll_id = await _stage_poll(session, current, runtime.llm_poll_interval_seconds)
                await _best_effort_dispatch(poll_id)
                return str(state)
            if state in {"failed", "cancelled", "partially_succeeded"}:
                raise ProviderError(
                    "llm_provider_task_failed",
                    f"provider task ended as {state}",
                    retryable=False,
                )
            if state != "succeeded":
                raise ProviderError(
                    "llm_provider_response", f"unknown provider state: {state}", retryable=True
                )
            result_text, _ = await chat_client.task_result(provider_task_id)
        finally:
            await chat_client.close()
        completed_at = datetime.now(UTC)
        async with session_scope(tenant_id) as session:
            current = (
                await session.execute(
                    select(AnalysisStep).where(AnalysisStep.id == step_id).with_for_update()
                )
            ).scalar_one_or_none()
            if current is None or current.status == "succeeded":
                return "already_completed"
            current.status = "succeeded"
            current.result_text = result_text
            current.completed_at = completed_at
            if current.submitted_at:
                llm_provider_wait_seconds.observe(
                    max((completed_at - current.submitted_at).total_seconds(), 0.0)
                )
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="llm",
                status="running",
                progress_pct=78,
                message="نتیجه مرحله تحلیل از سرویس هوش مصنوعی دریافت شد",
                step_key=f"{current.id}:completed",
            )
        await _advance(tenant_id, run.id, step_id)
        return "completed"
    except Exception as exc:
        return await _retry_or_fail_step(tenant_id, step_id, exc, phase="poll")


async def _advance(tenant_id: UUID, run_id: UUID, completed_step_id: UUID) -> None:
    dispatch_id: UUID | None = None
    dispatch_ids: list[UUID] = []
    final_result: ExtractionResult | None = None
    final_raw: str | None = None
    failure: Exception | None = None
    async with session_scope(tenant_id) as session:
        run = (
            await session.execute(
                select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return
        completed = await session.get(AnalysisStep, completed_step_id)
        if completed is None:
            return
        workflow = dict(run.result or {})
        steps = list(
            (
                await session.execute(
                    select(AnalysisStep)
                    .where(AnalysisStep.analysis_run_id == run_id)
                    .order_by(AnalysisStep.kind, AnalysisStep.ordinal)
                )
            ).scalars()
        )
        if completed.kind == "map":
            maps = [step for step in steps if step.kind == "map"]
            if not maps or any(step.status != "succeeded" for step in maps):
                return
            joined = f"{REDUCE_HEADER}\n" + "\n".join(
                f"[بخش {index}] {(step.result_text or '').strip()}"
                for index, step in enumerate(maps, start=1)
            )
            if workflow.get("_extra_reduce"):
                _, dispatch_id = await _create_step(
                    session,
                    run=run,
                    kind="reduce",
                    ordinal=0,
                    system_prompt=MAP_INSTRUCTION,
                    input_text=joined,
                )
            else:
                _, dispatch_id = await _create_step(
                    session,
                    run=run,
                    kind="extract",
                    ordinal=0,
                    system_prompt=load_run_prompt(run.prompt_version, run.system_prompt),
                    input_text=joined,
                )
        elif completed.kind == "reduce":
            body = f"{REDUCE_HEADER}\n{(completed.result_text or '').strip()}"
            _, dispatch_id = await _create_step(
                session,
                run=run,
                kind="extract",
                ordinal=0,
                system_prompt=load_run_prompt(run.prompt_version, run.system_prompt),
                input_text=body,
            )
        elif completed.kind in {"extract", "repair"}:
            raw = completed.result_text or ""
            try:
                final_result = ExtractionResult.model_validate(extract_json(raw))
                final_raw = raw
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                if completed.kind == "repair":
                    failure = RuntimeError(f"llm json invalid after repair: {exc!r}")
                else:
                    repair_system, repair_body = build_repair_request(raw)
                    _, dispatch_id = await _create_step(
                        session,
                        run=run,
                        kind="repair",
                        ordinal=0,
                        system_prompt=repair_system,
                        input_text=repair_body,
                    )
    if dispatch_ids:
        for staged_id in dispatch_ids:
            await _best_effort_dispatch(staged_id)
    elif dispatch_id is not None:
        await _best_effort_dispatch(dispatch_id)
    elif final_result is not None and final_raw is not None:
        await _finalize(tenant_id, run_id, final_result, final_raw)
    elif failure is not None:
        await _fail_run(tenant_id, run_id, failure)


async def _finalize(tenant_id: UUID, run_id: UUID, result: ExtractionResult, raw: str) -> None:
    notify_id: UUID | None = None
    async with session_scope(tenant_id) as session:
        run = await session.get(AnalysisRun, run_id)
        if run is None:
            return
        call_id = run.call_id
        workflow = dict(run.result or {})
    async with session_scope(tenant_id) as session:
        job = await _latest_job(session, tenant_id, call_id, lock=True)
        if job is None or job.status == "succeeded":
            return
        call = await session.get(Call, call_id)
        run = await session.get(AnalysisRun, run_id)
        if call is None or run is None:
            return
        insight = await session.get(CallInsight, call_id)
        if insight is None:
            insight = CallInsight(call_id=call_id, tenant_id=tenant_id)
            session.add(insight)
        insight.summary = result.summary
        insight.keywords = result.keywords
        insight.sentiment = result.sentiment.overall
        insight.sentiment_score = result.sentiment.score
        text_profile = result.sentiment.profile().text
        assert text_profile is not None
        insight.sentiment_profile = merge_sentiment_profile(
            insight.sentiment_profile,
            text=text_profile.model_dump(mode="json"),
        )
        insight.intent = result.intent
        insight.topics = result.topics
        insight.ner = result.ner.model_dump(mode="json")
        insight.action_items = result.action_items
        sales_insight = await sales_insights.sync_from_extraction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            analysis_run_id=run_id,
            result=result,
        )
        await session.flush()
        await knowledge.index_call(session, tenant_id, call_id)
        await follow_up_tasks.sync_from_analysis(session, call, result.action_items)
        run.raw_output = raw
        run.result = {
            **result.model_dump(mode="json"),
            "taxonomy_version": sales_insight.taxonomy_version,
        }
        run.status = "succeeded"
        await pipeline.mark_job(
            session, tenant_id=tenant_id, call_id=call_id, kind="llm", status="succeeded"
        )
        if bool(workflow.get("_reanalysis")):
            previous = workflow.get("_previous_status")
            restored = (
                str(previous) if previous and not str(previous).startswith("failed") else "complete"
            )
            call.status = restored
            call.error_code = None
            values = progress.values_for_status(restored)
            if "progress_pct" in values:
                call.progress_pct = int(values["progress_pct"])
            call.progress_detail = str(values["progress_detail"])
            call.updated_at = datetime.now(UTC)
            return
        billed = await billing.settle(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            actual_duration_ms=int(workflow.get("_duration_ms") or call.duration_ms),
        )
        call.billed_seconds = billed
        call.status = "billed"
        call.error_code = None
        values = progress.values_for_status("billed")
        call.progress_pct = int(values["progress_pct"])
        call.progress_detail = str(values["progress_detail"])
        call.updated_at = datetime.now(UTC)
        notify_job = Job(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="notify",
            status="queued",
            attempt=0,
        )
        session.add(notify_job)
        await session.flush()
        await processing_events.record(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="notify",
            status="queued",
            progress_pct=90,
            message="اطلاع‌رسانی در صف پردازش قرار گرفت",
            step_key=f"{notify_job.id}:queued:0",
        )
        notify_id = await outbox.stage_job(
            session,
            job_id=notify_job.id,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="notify",
            event="call.complete",
            available_at=datetime.now(UTC) + timedelta(hours=1),
        )
    try:
        await queue.enqueue_raw(
            queue.QUEUE_LLM,
            "score_operator_call",
            {
                "tenant_id": str(tenant_id),
                "call_id": str(call_id),
                "analysis_run_id": str(run_id),
                "notify_outbox_id": str(notify_id) if notify_id else None,
            },
        )
    except Exception:
        logger.exception("failed to enqueue operator score")


async def _retry_or_fail_step(tenant_id: UUID, step_id: UUID, exc: Exception, *, phase: str) -> str:
    code, detail, retryable = classify_failure(exc, kind="llm")
    dispatch_id: UUID | None = None
    run_id: UUID | None = None
    async with session_scope(tenant_id) as session:
        step = await session.get(AnalysisStep, step_id)
        if step is None:
            return "missing"
        step.attempt += 1
        step.error_code = code
        step.error_detail = detail[:2000]
        run_id = step.analysis_run_id
        if retryable and step.attempt < 4:
            step.status = "queued" if phase == "submit" else "submitted"
            function = "submit_analysis_step" if phase == "submit" else "poll_analysis_step"
            dispatch_id = await outbox.stage(
                session,
                tenant_id=step.tenant_id,
                queue_name=queue.QUEUE_LLM,
                function_name=function,
                payload={"tenant_id": str(tenant_id), "step_id": str(step.id)},
                available_at=datetime.now(UTC) + timedelta(seconds=2**step.attempt),
            )
        else:
            step.status = "failed"
            step.completed_at = datetime.now(UTC)
    if dispatch_id is not None:
        await _best_effort_dispatch(dispatch_id)
        return "retry_scheduled"
    assert run_id is not None
    await _fail_run(tenant_id, run_id, exc)
    return "failed"


async def _fail_run(tenant_id: UUID, run_id: UUID, exc: Exception) -> None:
    code, detail, retryable = classify_failure(exc, kind="llm")
    async with session_scope(tenant_id) as session:
        run = await session.get(AnalysisRun, run_id)
        if run is None:
            return
        call_id = run.call_id
        workflow = dict(run.result or {})
        run.status = "failed"
    reanalysis = bool(workflow.get("_reanalysis"))
    retried = await pipeline.handle_failure(
        tenant_id=tenant_id,
        call_id=call_id,
        kind="llm",
        error_code=code,
        error_detail=detail,
        analysis_run_id=run_id,
        reanalysis=reanalysis,
        previous_status=workflow.get("_previous_status"),
        retryable=retryable,
    )
    if reanalysis and not retried:
        previous = workflow.get("_previous_status")
        restored = (
            str(previous) if previous and not str(previous).startswith("failed") else "complete"
        )
        async with session_scope(tenant_id) as session:
            call = await session.get(Call, call_id)
            if call is not None and call.status == "analyzing":
                call.status = restored
                call.error_code = None
                values = progress.values_for_status(restored)
                if "progress_pct" in values:
                    call.progress_pct = int(values["progress_pct"])
                call.progress_detail = str(values["progress_detail"])
                call.updated_at = datetime.now(UTC)


async def _stage_poll(session: Any, step: AnalysisStep, delay: float) -> UUID:
    return await outbox.stage(
        session,
        tenant_id=step.tenant_id,
        queue_name=queue.QUEUE_LLM,
        function_name="poll_analysis_step",
        payload={"tenant_id": str(step.tenant_id), "step_id": str(step.id)},
        available_at=datetime.now(UTC) + timedelta(seconds=delay),
    )


async def _latest_job(
    session: Any, tenant_id: UUID, call_id: UUID, *, lock: bool = False
) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.tenant_id == tenant_id, Job.call_id == call_id, Job.kind == "llm")
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    job: Job | None = (await session.execute(stmt)).scalar_one_or_none()
    return job


async def _best_effort_dispatch(outbox_id: UUID) -> None:
    try:
        await outbox.dispatch_one(outbox_id)
    except Exception:
        logger.exception(
            "immediate durable analysis dispatch failed",
            extra={"extra_fields": {"outbox_id": str(outbox_id)}},
        )
