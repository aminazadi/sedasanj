from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select

from app.db import operational_tenant_ids, session_scope
from app.metrics import jobs_failed_retryable, oldest_job_seconds, provider_tasks, queue_depth
from app.models import (
    AnalysisRun,
    AnalysisStep,
    AudioObject,
    Call,
    CreditGrant,
    Job,
    LedgerEntry,
    Order,
    OrderItem,
    PlanVersion,
    Subscription,
    SubscriptionChange,
    TenantBalanceCache,
    User,
)
from app.services import commerce, outbox, pipeline, queue
from app.services.commerce_settings import get_commerce_settings
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(seconds=30)
# Running workers have a 30-35 minute ARQ timeout. Re-enqueueing them early creates
# duplicate provider calls because worker claims also accept active states for recovery.
RUNNING_STUCK_AFTER = timedelta(minutes=40)
QUEUED_STATES = {
    "stored": "asr",
    "emotion_queued": "emotion",
    "transcribed": "llm",
    "analyzed": "llm",
    "billed": "notify",
    "notified": "notify",
}
RUNNING_STATES = {
    "transcribing": "asr",
    "emotion_analyzing": "emotion",
    "analyzing": "llm",
}
IN_FLIGHT = {**QUEUED_STATES, **RUNNING_STATES}
RETRY_KIND_STATUS = {
    "asr": "asr",
    "emotion": "emotion",
    "llm": "llm",
    "notify": "notify",
}


async def expire_commerce_state() -> tuple[int, int]:
    now = datetime.now(UTC)
    expired_subscriptions = 0
    expired_grants = 0
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            subscriptions = (
            await session.execute(
                select(Subscription)
                .where(
                    Subscription.status.in_(("active", "trialing")),
                    Subscription.period_end <= now,
                )
                .with_for_update()
            )
            ).scalars().all()
            for subscription in subscriptions:
                subscription.status = (
                    "canceled" if subscription.cancel_at_period_end else "expired"
                )
                subscription.updated_at = now
                expired_subscriptions += 1

            grants = (
            await session.execute(
                select(CreditGrant)
                .where(
                    CreditGrant.expires_at.is_not(None),
                    CreditGrant.expires_at <= now,
                    CreditGrant.remaining_seconds > 0,
                )
                .with_for_update()
            )
            ).scalars().all()
            for grant in grants:
                amount = grant.remaining_seconds
                cache = await session.get(
                    TenantBalanceCache, grant.tenant_id, with_for_update=True
                )
                if cache is not None:
                    cache.seconds = max(0, int(cache.seconds or 0) - amount)
                grant.remaining_seconds = 0
                session.add(
                    LedgerEntry(
                        tenant_id=grant.tenant_id,
                        call_id=None,
                        kind="expiration",
                        seconds_delta=-amount,
                        toman_delta=0,
                        idempotency_key=f"expire:{grant.id}",
                    )
                )
                expired_grants += 1
    return expired_subscriptions, expired_grants


async def prepare_renewal_orders() -> int:
    now = datetime.now(UTC)
    created = 0
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            settings = await get_commerce_settings(session)
            until = now + timedelta(days=settings.renewal_lead_days)
            subscriptions = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.status == "active",
                        Subscription.billing_period.in_(("monthly", "annual")),
                        Subscription.cancel_at_period_end.is_(False),
                        Subscription.period_end > now,
                        Subscription.period_end <= until,
                    )
                )
            ).scalars().all()
            for subscription in subscriptions:
                idem = f"renewal:{subscription.id}:{subscription.period_end.isoformat()}"
                exists = (
                    await session.execute(
                        select(Order.id).where(
                            Order.tenant_id == subscription.tenant_id,
                            Order.idempotency_key == idem,
                        )
                    )
                ).scalar_one_or_none()
                if exists is not None:
                    continue
                version_id = subscription.next_plan_version_id or subscription.plan_version_id
                version = await session.get(PlanVersion, version_id)
                if version is None:
                    continue
                extra = subscription.extra_operators
                scheduled = (
                    await session.execute(
                        select(SubscriptionChange)
                        .where(
                            SubscriptionChange.subscription_id == subscription.id,
                            SubscriptionChange.status == "scheduled",
                        )
                        .order_by(SubscriptionChange.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if scheduled is not None and scheduled.requested_extra_operators is not None:
                    extra = scheduled.requested_extra_operators
                amount, extra_unit = commerce.subscription_amount(
                    version, subscription.billing_period, extra
                )
                admin = (
                    await session.execute(
                        select(User)
                        .where(
                            User.tenant_id == subscription.tenant_id,
                            User.role == "org_admin",
                        )
                        .order_by(User.created_at)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if admin is None:
                    continue
                order = Order(
                    tenant_id=subscription.tenant_id,
                    number=f"RN-{now:%Y%m%d}-{secrets.token_hex(4).upper()}",
                    kind="renewal",
                    status="draft",
                    amount_toman=amount,
                    callback_token=secrets.token_urlsafe(32),
                    idempotency_key=idem,
                    customer_name=admin.display_name or admin.email,
                    customer_email=admin.email,
                    customer_mobile=admin.mobile_number or "",
                    invoice_profile={},
                )
                session.add(order)
                await session.flush()
                base_amount = amount - extra * extra_unit
                session.add(
                    OrderItem(
                        order_id=order.id,
                        tenant_id=subscription.tenant_id,
                        kind="subscription",
                        description="تمدید اشتراک",
                        quantity=1,
                        unit_price_toman=base_amount,
                        total_toman=base_amount,
                        metadata_json={
                            "plan_version_id": str(version.id),
                            "billing_period": subscription.billing_period,
                        },
                    )
                )
                if extra:
                    session.add(
                        OrderItem(
                            order_id=order.id,
                            tenant_id=subscription.tenant_id,
                            kind="extra_operator",
                            description="اپراتور اضافه تمدید",
                            quantity=extra,
                            unit_price_toman=extra_unit,
                            total_toman=extra * extra_unit,
                            metadata_json={},
                        )
                    )
                created += 1
    return created


def reanalysis_recovery_context(
    call: Call, latest_run: AnalysisRun | None, run_count: int
) -> tuple[bool, str | None]:
    if call.status != "analyzing":
        return False, None
    metadata = latest_run.result if latest_run is not None and latest_run.result else {}
    tagged = metadata.get("_reanalysis") is True
    legacy = "_reanalysis" not in metadata and run_count > 1
    if not (tagged or legacy):
        return False, None
    previous = metadata.get("_previous_status")
    if isinstance(previous, str) and previous:
        return True, previous
    return True, "complete" if call.billed_seconds is not None else "transcribed"


async def run_retention() -> int:
    """§13 retention: drop MinIO objects past `audio_objects.expires_at`; keep transcripts."""
    storage = get_storage()
    deleted = 0
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            rows = (
                (
                    await session.execute(
                        select(AudioObject).where(
                            AudioObject.deleted_at.is_(None),
                            AudioObject.expires_at.is_not(None),
                            AudioObject.expires_at < datetime.now(UTC),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for audio in rows:
                await storage.delete(audio.object_key)
                audio.deleted_at = datetime.now(UTC)
                deleted += 1
    if deleted:
        logger.info("retention deleted audio", extra={"extra_fields": {"objects": deleted}})
    return deleted


async def reconcile_stuck_calls() -> int:
    """§6 reconciler: re-enqueue rows that stalled between a commit and an ARQ enqueue."""
    now = datetime.now(UTC)
    queued_cutoff = now - STUCK_AFTER
    running_cutoff = now - RUNNING_STUCK_AFTER
    requeued = 0
    stuck: list[tuple[UUID, UUID, str, str, str, bool, str | None]] = []
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            rows = (
            (
                await session.execute(
                    select(Call).where(
                        (
                            Call.status.in_(tuple(QUEUED_STATES))
                            & (Call.updated_at < queued_cutoff)
                        )
                        | (
                            Call.status.in_(tuple(RUNNING_STATES))
                            & (Call.updated_at < running_cutoff)
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
            call_ids = [call.id for call in rows]
            run_counts: dict[UUID, int] = {}
            if call_ids:
                count_rows = (
                await session.execute(
                    select(AnalysisRun.call_id, func.count(AnalysisRun.id))
                    .where(AnalysisRun.call_id.in_(call_ids))
                    .group_by(AnalysisRun.call_id)
                )
                ).all()
                for call_id, count in count_rows:
                    run_counts[call_id] = count
            latest_runs: dict[UUID, AnalysisRun] = {}
            if call_ids:
                analysis_runs = (
                (
                    await session.execute(
                        select(AnalysisRun)
                        .where(AnalysisRun.call_id.in_(call_ids))
                        .order_by(AnalysisRun.call_id, AnalysisRun.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
                for run in analysis_runs:
                    latest_runs.setdefault(run.call_id, run)
            for call in rows:
                reanalysis, previous_status = reanalysis_recovery_context(
                    call, latest_runs.get(call.id), int(run_counts.get(call.id, 0))
                )
                stuck.append(
                    (
                        tenant_id,
                        call.id,
                        IN_FLIGHT[call.status],
                        call.status,
                        f"recovery:{IN_FLIGHT[call.status]}:{call.id}:"
                        f"{call.status}:{int(call.updated_at.timestamp())}",
                        reanalysis,
                        previous_status,
                    )
                )
            overdue = (
            (
                await session.execute(
                    select(Job).where(
                        Job.status == "failed_retryable",
                        Job.run_after < now,
                    )
                )
            )
            .scalars()
            .all()
        )
            known = {call_id for _, call_id, _, _, _, _, _ in stuck}
            stuck.extend(
                (
                    tenant_id,
                    job.call_id,
                    RETRY_KIND_STATUS[job.kind],
                    "failed_retryable",
                    f"retry:{job.kind}:{job.call_id}:{job.attempt}",
                    False,
                    None,
                )
                for job in overdue
                if job.call_id not in known and job.kind in RETRY_KIND_STATUS
            )

    for tenant_id, call_id, kind, status, _job_id, reanalysis, previous_status in stuck:
        async with session_scope(tenant_id) as session:
            recovered_call = await session.get(Call, call_id)
            if recovered_call is None:
                continue
            analysis_run_id: UUID | None = None
            if kind == "emotion":
                analysis_run_id = (
                    await session.execute(
                        select(AnalysisRun.id)
                        .where(
                            AnalysisRun.call_id == call_id,
                            AnalysisRun.tenant_id == recovered_call.tenant_id,
                        )
                        .order_by(AnalysisRun.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if analysis_run_id is None:
                    logger.error(
                        "cannot recover emotion job without an analysis run",
                        extra={"extra_fields": {"call_id": str(call_id)}},
                    )
                    continue
            job = await pipeline.mark_job(
                session,
                tenant_id=recovered_call.tenant_id,
                call_id=call_id,
                kind=kind,
                status="queued",
            )
            staged_id = await outbox.stage_job(
                session,
                job_id=job.id,
                tenant_id=recovered_call.tenant_id,
                call_id=call_id,
                kind=kind,
                analysis_run_id=analysis_run_id,
                recovery=True,
                reanalysis=reanalysis,
                previous_status=previous_status,
                event="call.complete" if kind == "notify" else None,
            )
        await outbox.dispatch_one(staged_id, tenant_id)
        requeued += 1
        logger.warning(
            "requeued stuck call",
            extra={"extra_fields": {"call_id": str(call_id), "status": status, "kind": kind}},
        )
    return requeued


async def refresh_failure_gauge() -> None:
    """§14 alerting input: how many jobs are waiting for another attempt."""
    total = 0
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            total += int(
                (
                    await session.execute(
                        select(func.count(Job.id)).where(Job.status == "failed_retryable")
                    )
                ).scalar_one()
            )
    jobs_failed_retryable.set(total)


async def refresh_queue_depth() -> None:
    q = queue.get_queue()
    for name in (queue.QUEUE_ASR, queue.QUEUE_EMOTION, queue.QUEUE_LLM, queue.QUEUE_NOTIFY):
        queue_depth.labels(queue=name).set(await q.depth(name))
    now = datetime.now(UTC)
    oldest: dict[str, datetime] = {}
    counts: dict[str, int] = {}
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            rows = (
                await session.execute(
                    select(Job.kind, func.min(Job.queued_at))
                    .where(Job.status == "queued")
                    .group_by(Job.kind)
                )
            ).all()
            provider_rows = (
                await session.execute(
                    select(AnalysisStep.status, func.count(AnalysisStep.id)).group_by(
                        AnalysisStep.status
                    )
                )
            ).all()
            for kind, queued_at in rows:
                key = str(kind)
                if queued_at is not None and (key not in oldest or queued_at < oldest[key]):
                    oldest[key] = queued_at
            for task_status, total in provider_rows:
                key = str(task_status)
                counts[key] = counts.get(key, 0) + int(total)
    for kind in ("asr", "emotion", "llm", "notify"):
        queued_at = oldest.get(kind)
        oldest_job_seconds.labels(kind=kind).set(
            max((now - queued_at).total_seconds(), 0.0) if queued_at else 0.0
        )
    for status in ("queued", "submitted", "polling", "succeeded", "failed"):
        provider_tasks.labels(status=status).set(counts.get(status, 0))
