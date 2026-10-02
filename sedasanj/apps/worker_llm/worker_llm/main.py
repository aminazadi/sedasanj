from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import dispose_engine, resolve_tenant_for_call, session_scope
from app.logging import configure_logging, log_context
from app.metrics import llm_json_failures_total, start_metrics_server
from app.models import (
    AnalysisRun,
    Call,
    CallInsight,
    Job,
    JobOutbox,
    Tenant,
    TenantBalanceCache,
    Transcript,
)
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
from app.services.operator_scoring import score_call
from app.services.platform import (
    effective_extract_prompt,
    effective_models,
    resolve_provider_settings,
)
from app.services.provider_errors import classify_failure
from worker_llm.chunking import plan_chunks
from worker_llm.client import LlmClient, build_client, extract_json, load_run_prompt
from worker_llm.correction import poll_transcript_correction, start_transcript_correction
from worker_llm.durable import poll_analysis_step, start_analysis, submit_analysis_step
from worker_llm.prompts import build_repair_request

logger = logging.getLogger(__name__)

MAP_INSTRUCTION = (
    "این بخشی از یک مکالمه تلفنی فارسی است. آن را در حداکثر ۵ جمله فارسی خلاصه کن "
    "و نکات کلیدی، مبالغ، تاریخ‌ها و کارهای قابل پیگیری را حفظ کن. فقط متن خلاصه را بنویس."
)
REDUCE_HEADER = "خلاصه بخش‌های مکالمه (به ترتیب):"


def _claimable_call_statuses(*, reanalysis: bool, recovery: bool) -> tuple[str, ...]:
    if reanalysis:
        # Reanalysis is queued after the API has made the call visibly in-progress.
        # Job-row ownership prevents a duplicate delivery from also accepting it.
        return pipeline.REANALYSIS_STATES
    if recovery:
        return ("transcribed", "failed_retryable", "analyzing")
    return ("transcribed", "failed_retryable")


def _claimable_job_statuses(*, recovery: bool) -> tuple[str, ...]:
    if recovery:
        return ("queued", "failed_retryable", "running")
    return ("queued", "failed_retryable")


def _status_after_successful_reanalysis(previous_status: str | None) -> str:
    """Return the user-visible state after a reanalysis has produced an insight.

    Reanalysis normally restores a settled state such as ``complete`` or
    ``billed``.  A failed state is different: retaining it after a successful
    run leaves the call page reporting a stale failure even though the new
    insight is available.  Such calls have no successful state to restore, so
    mark them complete without charging a second time.
    """
    if previous_status and not previous_status.startswith("failed"):
        return previous_status
    return "complete"


async def _report(tenant_id: UUID, call_id: UUID, pct: int, detail: str) -> None:
    async with session_scope(tenant_id) as session:
        await progress.report(
            session,
            call_id=call_id,
            tenant_id=tenant_id,
            pct=pct,
            detail=detail,
            kind="llm",
        )


async def _map_reduce_text(
    client: LlmClient, chunks: list[str], extra_reduce: bool, model: str
) -> str:
    summaries: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        summary = await client.complete(MAP_INSTRUCTION, chunk, json_object=False, model=model)
        summaries.append(f"[بخش {index}] {summary.strip()}")
    joined = f"{REDUCE_HEADER}\n" + "\n".join(summaries)
    if extra_reduce:
        condensed = await client.complete(MAP_INSTRUCTION, joined, json_object=False, model=model)
        joined = f"{REDUCE_HEADER}\n{condensed.strip()}"
    return joined


async def _extract(
    client: LlmClient, system: str, body: str, model: str
) -> tuple[ExtractionResult, str]:
    raw = await client.complete(system, body, model=model)
    try:
        return ExtractionResult.model_validate(extract_json(raw)), raw
    except (ValidationError, ValueError, json.JSONDecodeError) as first:
        llm_json_failures_total.labels(stage="first").inc()
        logger.warning("llm json invalid, attempting one repair", extra={"extra_fields": {}})
        repair_system, repair_body = build_repair_request(raw)
        repaired = await client.complete(repair_system, repair_body, model=model)
        try:
            return ExtractionResult.model_validate(extract_json(repaired)), repaired
        except (ValidationError, ValueError, json.JSONDecodeError) as second:
            llm_json_failures_total.labels(stage="repair").inc()
            raise RuntimeError(
                f"llm json invalid after repair: {second!r} (first: {first!r})"
            ) from second


async def _run_model_analysis(
    *,
    client: LlmClient | None,
    runtime: Settings,
    tenant_id: UUID,
    call_id: UUID,
    text: str,
    prompt_version: str,
    system_prompt: str | None,
    model: str,
    run_id: UUID,
) -> tuple[ExtractionResult, str]:
    owned_client = False
    if runtime.llm_client in {"voicesanj", "llama"}:
        client = build_client(runtime, request_namespace=str(run_id))
        owned_client = True
    if client is None:
        raise RuntimeError("LLM client was not initialized")
    try:
        await _report(tenant_id, call_id, 62, "در حال آماده‌سازی متن مکالمه")
        await _report(tenant_id, call_id, 68, "متن آماده شد؛ در حال برنامه‌ریزی تحلیل")
        system = load_run_prompt(prompt_version, system_prompt)
        plan = plan_chunks(text)
        body = (
            plan.chunks[0]
            if plan.strategy == "single"
            else await _map_reduce_text(client, plan.chunks, plan.extra_reduce, model)
        )
        await _report(tenant_id, call_id, 76, "در حال استخراج نتیجه ساختاریافته")
        return await _extract(client, system, body, model)
    finally:
        if owned_client:
            await client.close()


async def analyze_call(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    call_id = UUID(str(payload["call_id"]))
    run_id_raw = payload.get("analysis_run_id")
    reanalysis = bool(payload.get("reanalysis", False))
    recovery = bool(payload.get("recovery", False))
    previous_status_raw = payload.get("previous_status")
    client: LlmClient | None = ctx.get("client")
    tenant_hint = UUID(str(payload["tenant_id"])) if payload.get("tenant_id") else None
    tenant_id = await resolve_tenant_for_call(call_id, tenant_hint)
    if tenant_id is None:
        return "missing"
    async with session_scope(tenant_id) as session:
        call = await session.get(Call, call_id)
        if call is None:
            return "missing"
        prior_status = call.status
    log_context(tenant_id=str(tenant_id), call_id=str(call_id))

    # §11 reanalysis re-runs a finished call: it must not re-bill and must restore the state.
    expected = _claimable_call_statuses(reanalysis=reanalysis, recovery=recovery)
    claimable_job_statuses = _claimable_job_statuses(recovery=recovery)

    deferred_outbox_id: UUID | None = None
    async with session_scope(tenant_id) as session:
        tenant = await session.get(Tenant, tenant_id)
        tenant_limit = (
            tenant.max_concurrent_jobs
            if tenant is not None
            else get_settings().max_concurrent_llm_submissions
        )
        queued_job = await pipeline.lock_job_for_claim(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            expected=claimable_job_statuses,
        )
        if queued_job is None:
            return "skipped"
        has_tenant_slot = await pipeline.concurrency_slot_free(
            session, tenant_id, tenant_limit, kind="llm"
        )
        has_global_slot = await pipeline.global_analysis_slot_free(
            session,
            job_id=queued_job.id,
            limit=(await resolve_provider_settings(session)).analysis_concurrency,
        )
        if not has_tenant_slot or not has_global_slot:
            deferred_outbox_id = await outbox.stage_job(
                session,
                job_id=queued_job.id,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="llm",
                analysis_run_id=UUID(str(run_id_raw)) if run_id_raw else None,
                reanalysis=reanalysis,
                previous_status=str(previous_status_raw) if previous_status_raw else None,
                recovery=recovery,
                available_at=datetime.now(UTC) + timedelta(seconds=5),
            )
        else:
            claimed = await pipeline.claim_call(
                session,
                call_id,
                tenant_id=tenant_id,
                expected=expected,
                next_status="analyzing",
            )
            if claimed is None:
                logger.info("llm call state is not claimable")
                return "skipped"
            transcript = (
                await session.execute(
                    select(Transcript).where(
                        Transcript.call_id == call_id, Transcript.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if transcript is None:
                raise RuntimeError("call has no transcript")
            text = transcript.corrected_text or transcript.full_text
            duration_ms = claimed.duration_ms
            previous_status = (
                str(previous_status_raw)
                if reanalysis and previous_status_raw
                else (prior_status if reanalysis and prior_status != "analyzing" else None)
            )
            run = (
                await _load_run(session, call_id, tenant_id, run_id_raw)
                if run_id_raw
                else (
                    await session.execute(
                        select(AnalysisRun)
                        .where(
                            AnalysisRun.call_id == call_id,
                            AnalysisRun.tenant_id == tenant_id,
                        )
                        .order_by(AnalysisRun.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            )
            if run is None:
                models = await effective_models(session)
                run = AnalysisRun(
                    call_id=call_id,
                    tenant_id=tenant_id,
                    llm_model=models["llm_model"],
                    prompt_version=models["prompt_version"],
                    system_prompt=await effective_extract_prompt(session, models["prompt_version"]),
                    status="pending",
                )
                session.add(run)
                await session.flush()
            run.status = "running"
            run_id = run.id
            prompt_version = run.prompt_version
            run_system_prompt = run.system_prompt
            run_llm_model = run.llm_model
            await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="llm", status="running"
            )
    if deferred_outbox_id is not None:
        await outbox.dispatch_one(deferred_outbox_id)
        return "deferred"

    try:
        async with session_scope(None, staff=True) as session:
            runtime = await resolve_provider_settings(session)
        if runtime.llm_client == "voicesanj":
            return await start_analysis(
                tenant_id=tenant_id,
                call_id=call_id,
                run_id=run_id,
                text=text,
                duration_ms=duration_ms,
                reanalysis=reanalysis,
                previous_status=previous_status,
            )
        settings = get_settings()
        async with asyncio.timeout(max(settings.analysis_timeout_seconds, 60.0)):
            result, raw = await _run_model_analysis(
                client=client,
                runtime=runtime,
                tenant_id=tenant_id,
                call_id=call_id,
                text=text,
                prompt_version=prompt_version,
                system_prompt=run_system_prompt,
                model=run_llm_model,
                run_id=run_id,
            )

        notify_outbox_id: UUID | None = None
        async with session_scope(tenant_id) as session:
            # Keep the lock order consistent with claim/failure paths (job, then call).
            # The status is not externally visible until this whole transaction commits.
            await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="llm", status="succeeded"
            )
            run = (
                await session.execute(
                    select(AnalysisRun).where(
                        AnalysisRun.id == run_id, AnalysisRun.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if run is not None:
                run.raw_output = raw
                run.result = result.model_dump(mode="json")
                run.status = "succeeded"

            insight = (
                await session.execute(
                    select(CallInsight).where(
                        CallInsight.call_id == call_id, CallInsight.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
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
            await sales_insights.sync_from_extraction(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                analysis_run_id=run_id,
                result=result,
            )
            await session.flush()
            await knowledge.index_call(session, tenant_id, call_id)

            call = (
                await session.execute(
                    select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            if call is not None:
                await follow_up_tasks.sync_from_analysis(session, call, result.action_items)
            if reanalysis:
                if call is not None:
                    restored = _status_after_successful_reanalysis(previous_status)
                    call.status = restored
                    call.error_code = None
                    restored_progress = progress.values_for_status(restored)
                    if "progress_pct" in restored_progress:
                        call.progress_pct = int(restored_progress["progress_pct"])
                    call.progress_detail = str(restored_progress["progress_detail"])
                    call.updated_at = datetime.now(UTC)
            else:
                billed = await billing.settle(
                    session, tenant_id=tenant_id, call_id=call_id, actual_duration_ms=duration_ms
                )
                if call is not None:
                    call.billed_seconds = billed
                    call.status = "billed"
                    call.error_code = None
                    billed_progress = progress.values_for_status("billed")
                    call.progress_pct = int(billed_progress["progress_pct"])
                    call.progress_detail = str(billed_progress["progress_detail"])
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
                notify_outbox_id = await outbox.stage_job(
                    session,
                    job_id=notify_job.id,
                    tenant_id=tenant_id,
                    call_id=call_id,
                    kind="notify",
                    event="call.complete",
                    available_at=datetime.now(UTC) + timedelta(hours=1),
                )

        if reanalysis:
            try:
                await queue.enqueue_raw(
                    queue.QUEUE_LLM,
                    "score_operator_call",
                    {
                        "tenant_id": str(tenant_id),
                        "call_id": str(call_id),
                        "analysis_run_id": str(run_id),
                        "notify_outbox_id": None,
                    },
                )
            except Exception:
                logger.exception("failed to enqueue operator score")
            return "reanalyzed"
        try:
            await queue.enqueue_raw(
                queue.QUEUE_LLM,
                "score_operator_call",
                {
                    "tenant_id": str(tenant_id),
                    "call_id": str(call_id),
                    "analysis_run_id": str(run_id),
                    "notify_outbox_id": str(notify_outbox_id),
                },
            )
        except Exception:
            logger.exception("failed to enqueue operator score")
        try:
            await _maybe_warn_low_balance(tenant_id)
        except Exception:  # noqa: BLE001 - low-balance warning is not part of call analysis
            logger.exception("failed to enqueue low balance warning")
        return "analyzed"
    except Exception as exc:  # noqa: BLE001 - retry policy owns the outcome
        code, detail, retryable = classify_failure(exc, kind="llm")
        async with session_scope(tenant_id) as session:
            run = (
                await session.execute(
                    select(AnalysisRun).where(
                        AnalysisRun.id == run_id, AnalysisRun.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if run is not None:
                run.status = "failed"
        if reanalysis:
            retried = await pipeline.handle_failure(
                tenant_id=tenant_id,
                call_id=call_id,
                kind="llm",
                error_code=code,
                error_detail=detail,
                analysis_run_id=run_id,
                reanalysis=True,
                previous_status=previous_status,
                retryable=retryable,
            )
            if retried:
                return "retry_scheduled"
            # A terminal reanalysis failure leaves the original insight and billing untouched (§11).
            async with session_scope(tenant_id) as session:
                await session.execute(
                    update(Call)
                    .where(
                        Call.id == call_id,
                        Call.tenant_id == tenant_id,
                        Call.status == "analyzing",
                    )
                    .values(
                        status=previous_status or "complete",
                        updated_at=datetime.now(UTC),
                        **progress.values_for_status(previous_status or "complete"),
                    )
                )
            logger.warning("reanalysis failed", extra={"extra_fields": {"error": repr(exc)}})
            return "reanalysis_failed"
        retried = await pipeline.handle_failure(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            error_code=code,
            error_detail=detail,
            analysis_run_id=run_id,
            retryable=retryable,
        )
        # handle_failure already requeued: re-raising would let ARQ add a second attempt (§6).
        return "retry_scheduled" if retried else "failed_terminal"


async def _load_run(
    session: AsyncSession, call_id: UUID, tenant_id: UUID, run_id_raw: object
) -> AnalysisRun | None:
    """Queue payloads are untrusted: a run only counts when it belongs to this call."""
    try:
        run_id = UUID(str(run_id_raw))
    except ValueError:
        return None
    run = (
        await session.execute(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id,
                AnalysisRun.call_id == call_id,
                AnalysisRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    return run


async def _maybe_warn_low_balance(tenant_id: UUID) -> None:
    """§10.4 `balance.low`: fires once a day while the tenant stays under the threshold."""
    settings = get_settings()
    async with session_scope(tenant_id) as session:
        cache = (
            await session.execute(
                select(TenantBalanceCache).where(TenantBalanceCache.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
    if cache is None or tenant is None or cache.seconds > settings.balance_low_threshold_seconds:
        return
    await queue.enqueue_balance_low(tenant_id)


async def score_operator_call(_: dict[str, Any], payload: dict[str, Any]) -> str:
    result = await score_call(
        UUID(str(payload["tenant_id"])),
        UUID(str(payload["call_id"])),
        UUID(str(payload["analysis_run_id"])),
    )
    notify_outbox_id = payload.get("notify_outbox_id")
    if notify_outbox_id:
        try:
            outbox_id = UUID(str(notify_outbox_id))
            async with session_scope(UUID(str(payload["tenant_id"]))) as session:
                await session.execute(
                    update(JobOutbox)
                    .where(JobOutbox.id == outbox_id)
                    .values(available_at=datetime.now(UTC))
                )
            await outbox.dispatch_one(outbox_id)
        except Exception:  # noqa: BLE001 - outbox reconciliation retries dispatch
            logger.exception("failed to enqueue notification after operator scoring")
    return result


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging("worker-llm", settings.log_level)
    start_metrics_server(settings)
    # HTTP-backed clients are rebuilt per job from DB-backed platform settings.
    # Only the fixture client is safe and useful to initialize before a DB session.
    ctx["client"] = (
        None if settings.llm_client in {"voicesanj", "llama"} else build_client(settings)
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    client: LlmClient | None = ctx.get("client")
    if client is not None:
        await client.close()
    await queue.get_queue().close()
    await dispose_engine()


class WorkerSettings:
    functions = [
        analyze_call,
        start_transcript_correction,
        poll_transcript_correction,
        submit_analysis_step,
        poll_analysis_step,
        score_operator_call,
    ]
    queue_name = queue.QUEUE_LLM
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 3
    job_timeout = 1800
    keep_result = 3600
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
