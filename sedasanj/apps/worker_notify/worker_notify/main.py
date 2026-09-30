from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import get_settings
from app.db import dispose_engine, resolve_tenant_for_call, session_scope
from app.errors import ApiError
from app.logging import configure_logging, log_context
from app.metrics import start_metrics_server, webhook_responses_total
from app.models import (
    Call,
    CallInsight,
    OperatorCallScore,
    SalesInsight,
    Tenant,
    TenantBalanceCache,
    User,
    Webhook,
    WebhookDelivery,
)
from app.security import sign_webhook
from app.services import outbox, pipeline, progress, queue
from app.services.maintenance import (
    expire_commerce_state,
    prepare_renewal_orders,
    reconcile_stuck_calls,
    refresh_failure_gauge,
    refresh_queue_depth,
    run_retention,
)
from app.services.urlguard import assert_safe_webhook_url_async
from worker_notify.mailer import send_email

logger = logging.getLogger(__name__)

EVENTS = ("call.complete", "call.failed", "balance.low", "sales.insight")


async def _build_payload(
    event: str, call_id: UUID, tenant_id: UUID
) -> tuple[UUID, dict[str, Any]] | None:
    async with session_scope(tenant_id) as session:
        call = await session.get(Call, call_id)
        if call is None:
            return None
        insight = (
            await session.execute(
                select(CallInsight).where(
                    CallInsight.call_id == call_id, CallInsight.tenant_id == call.tenant_id
                )
            )
        ).scalar_one_or_none()
        sales = await session.get(SalesInsight, call_id)
        score = (
            await session.execute(
                select(OperatorCallScore)
                .where(
                    OperatorCallScore.call_id == call_id,
                    OperatorCallScore.status == "succeeded",
                )
                .order_by(OperatorCallScore.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        data: dict[str, Any] = {
            "caller_number": call.caller_number,
            "duration_ms": call.duration_ms,
            "summary": insight.summary if insight else None,
            "sentiment": insight.sentiment if insight else None,
            "sentiment_profile": insight.sentiment_profile if insight else None,
            "intent": insight.intent if insight else None,
            "campaign_id": call.campaign_id,
            "source": call.source,
            "external_reference": call.external_reference,
            "sales": {
                "funnel_stage": sales.funnel_stage,
                "outcome": sales.outcome,
                "certainty": sales.certainty,
                "confidence": sales.confidence,
                "product": sales.product,
                "objections": sales.objections,
                "win_loss_reason": sales.win_loss_reason,
                "next_action": sales.next_action,
                "next_action_due_at": sales.next_action_due_at.isoformat()
                if sales.next_action_due_at
                else None,
                "evidence": sales.evidence,
            }
            if sales
            else None,
            "operator_score": score.total_score if score else None,
        }
        if event == "call.failed":
            data["error_code"] = call.error_code
        return call.tenant_id, {
            "event": event,
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tenant_id": str(call.tenant_id),
            "call_id": str(call_id),
            "data": data,
        }


async def _post_webhook(
    client: httpx.AsyncClient, hook: Webhook, payload: dict[str, Any]
) -> tuple[int | None, str | None]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "X-CBI-Timestamp": timestamp,
        "X-CBI-Signature": sign_webhook(hook.secret, timestamp, body),
        "X-CBI-Event": str(payload["event"]),
    }
    try:
        # Re-checked at delivery time because DNS can be repointed after registration (§12).
        await assert_safe_webhook_url_async(hook.url)
        response = await client.post(hook.url, content=body, headers=headers)
    except ApiError as exc:
        webhook_responses_total.labels(status="blocked").inc()
        return None, exc.message
    except httpx.HTTPError as exc:
        webhook_responses_total.labels(status="error").inc()
        return None, repr(exc)
    bucket = f"{response.status_code // 100}xx"
    webhook_responses_total.labels(status=bucket).inc()
    return response.status_code, None if response.is_success else response.text[:500]


async def _active_hooks(tenant_id: UUID, event: str) -> list[Webhook]:
    async with session_scope(tenant_id) as session:
        hooks = (
            (
                await session.execute(
                    select(Webhook).where(Webhook.tenant_id == tenant_id, Webhook.active.is_(True))
                )
            )
            .scalars()
            .all()
        )
    return [hook for hook in hooks if event in hook.events]


async def _record_delivery(
    tenant_id: UUID,
    hook_id: UUID,
    call_id: UUID | None,
    event: str,
    body: dict[str, Any],
    attempt: int,
    status_code: int | None,
    next_retry_at: datetime | None,
) -> None:
    async with session_scope(tenant_id) as session:
        session.add(
            WebhookDelivery(
                webhook_id=hook_id,
                tenant_id=tenant_id,
                call_id=call_id,
                event=event,
                payload=body,
                attempt=attempt,
                status_code=status_code,
                next_retry_at=next_retry_at,
            )
        )


async def _notify_balance_low(client: httpx.AsyncClient, tenant_id: UUID) -> str:
    settings = get_settings()
    async with session_scope(tenant_id) as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        cache = (
            await session.execute(
                select(TenantBalanceCache).where(TenantBalanceCache.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        admins = (
            (
                await session.execute(
                    select(User).where(User.tenant_id == tenant_id, User.role == "org_admin")
                )
            )
            .scalars()
            .all()
        )
    if tenant is None or cache is None:
        return "missing"

    body: dict[str, Any] = {
        "event": "balance.low",
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tenant_id": str(tenant_id),
        "call_id": None,
        "data": {"balance_seconds": cache.seconds, "balance_toman": cache.toman},
    }
    for hook in await _active_hooks(tenant_id, "balance.low"):
        status_code, _ = await _post_webhook(client, hook, body)
        await _record_delivery(tenant_id, hook.id, None, "balance.low", body, 1, status_code, None)

    subject = "هشدار اعتبار کم — CBI Voice Analytics"
    email_body = (
        f"اعتبار باقی‌مانده سازمان {tenant.name}: {cache.seconds // 60} دقیقه "
        f"({cache.toman} تومان). لطفاً حساب را شارژ کنید."
    )
    for admin in admins:
        await send_email(settings, admin.email, subject, email_body)
    return "emailed"


async def deliver_event(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    event = str(payload["event"])
    if event not in EVENTS:
        raise ValueError(f"unknown event {event}")
    client: httpx.AsyncClient = ctx["http"]

    if event == "balance.low":
        return await _notify_balance_low(client, UUID(str(payload["tenant_id"])))

    call_id = UUID(str(payload["call_id"]))
    tenant_hint = UUID(str(payload["tenant_id"])) if payload.get("tenant_id") else None
    resolved_tenant = await resolve_tenant_for_call(call_id, tenant_hint)
    if resolved_tenant is None:
        return "missing"
    built = await _build_payload(event, call_id, resolved_tenant)
    if built is None:
        return "missing"
    tenant_id, body = built
    log_context(tenant_id=str(tenant_id), call_id=str(call_id))

    try:
        deliveries = [(hook, event, body) for hook in await _active_hooks(tenant_id, event)]
        if event == "call.complete" and body["data"].get("sales") is not None:
            sales_body = {**body, "event": "sales.insight"}
            deliveries.extend(
                (hook, "sales.insight", sales_body)
                for hook in await _active_hooks(tenant_id, "sales.insight")
            )
        async with session_scope(tenant_id) as session:
            job = await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="notify", status="running"
            )
            attempt = job.attempt + 1
            if event == "call.complete":
                await progress.report(
                    session,
                    call_id=call_id,
                    tenant_id=tenant_id,
                    pct=95,
                    detail="در حال ارسال اطلاع‌رسانی",
                    kind="notify",
                )

        failures: list[str] = []
        for hook, delivery_event, delivery_body in deliveries:
            status_code, error = await _post_webhook(client, hook, delivery_body)
            next_retry_at = (
                datetime.now(UTC) + pipeline.backoff_for("notify", attempt)
                if error is not None
                else None
            )
            await _record_delivery(
                tenant_id,
                hook.id,
                call_id,
                delivery_event,
                delivery_body,
                attempt,
                status_code,
                next_retry_at,
            )
            if error is not None:
                failures.append(f"{hook.url}: {error}")

        if failures:
            raise RuntimeError("; ".join(failures)[:1000])

        async with session_scope(tenant_id) as session:
            call = (
                await session.execute(
                    select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            if call is not None and event == "call.complete":
                call.status = "complete"
                complete = progress.values_for_status("complete")
                call.progress_pct = int(complete["progress_pct"])
                call.progress_detail = str(complete["progress_detail"])
                call.updated_at = datetime.now(UTC)
            await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="notify", status="succeeded"
            )
        return "delivered"
    except Exception as exc:  # noqa: BLE001 - retry policy owns the outcome
        retried = await pipeline.handle_failure(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="notify",
            error_code="notify_failed",
            error_detail=repr(exc),
            event=event,
        )
        if not retried:
            logger.error("webhook dead-lettered", extra={"extra_fields": {"call_id": str(call_id)}})
        return "retry" if retried else "dead_letter"


async def retention_cron(ctx: dict[str, Any]) -> str:
    deleted = await run_retention()
    purged = await outbox.purge_dispatched()
    return f"retention:{deleted}:outbox:{purged}"


async def reconciler_cron(ctx: dict[str, Any]) -> str:
    requeued = await reconcile_stuck_calls()
    expired_subscriptions, expired_grants = await expire_commerce_state()
    renewal_orders = await prepare_renewal_orders()
    await refresh_failure_gauge()
    await refresh_queue_depth()
    return (
        f"reconciled:{requeued}:subscriptions:{expired_subscriptions}:"
        f"grants:{expired_grants}:renewals:{renewal_orders}"
    )


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging("worker-notify", settings.log_level)
    start_metrics_server(settings)
    ctx["http"] = httpx.AsyncClient(timeout=20.0, follow_redirects=False)
    try:
        recovered = await reconcile_stuck_calls()
        if recovered:
            logger.warning(
                "recovered stale calls on startup",
                extra={"extra_fields": {"calls": recovered}},
            )
    except Exception:  # noqa: BLE001 - startup should continue; cron retries within a minute
        logger.exception("startup reconciliation failed")


async def shutdown(ctx: dict[str, Any]) -> None:
    client: httpx.AsyncClient | None = ctx.get("http")
    if client is not None:
        await client.aclose()
    await queue.get_queue().close()
    await dispose_engine()


class WorkerSettings:
    functions = [deliver_event]
    cron_jobs = [
        cron(retention_cron, hour=2, minute=15),
        cron(reconciler_cron, second=30),
    ]
    queue_name = queue.QUEUE_NOTIFY
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 8
    job_timeout = 300
    keep_result = 3600
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
