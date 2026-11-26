from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import operational_tenant_ids, routable_tenant_ids, session_scope
from app.errors import ApiError
from app.metrics import (
    calls_stuck,
    jobs_failed_retryable,
    oldest_job_seconds,
    provider_tasks,
    queue_depth,
)
from app.models import (
    AnalysisRun,
    AnalysisStep,
    AsrTranscriptRevision,
    AudioObject,
    Call,
    CreditGrant,
    Job,
    JobOutbox,
    LedgerEntry,
    Meeting,
    MeetingChunk,
    Order,
    OrderItem,
    PaymentAttempt,
    Plan,
    PlanVersion,
    Subscription,
    SubscriptionChange,
    TenantBalanceCache,
    TranscriptRevision,
    User,
    WebhookDelivery,
)
from app.services import (
    audio_lifecycle,
    billing,
    commerce,
    jalase_accounts,
    outbox,
    pipeline,
    progress,
    queue,
    speaker_profiles,
    subscription_state,
)
from app.services.commerce_settings import get_commerce_settings

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(seconds=30)
# Running workers have a 30-35 minute ARQ timeout. Re-enqueueing them early creates
# duplicate provider calls because worker claims also accept active states for recovery.
RUNNING_STUCK_AFTER = timedelta(minutes=40)
QUEUED_STATES = {
    "stored": "asr",
    "correcting": "correction",
    "emotion_queued": "emotion",
    "transcribed": "llm",
    "billed": "notify",
    "notified": "notify",
}
RUNNING_STATES = {
    "transcribing": "asr",
    "emotion_analyzing": "emotion",
    "analyzing": "llm",
}
IN_FLIGHT = {**QUEUED_STATES, **RUNNING_STATES}
# Call states from which a queued job of each kind can still be claimed. A queued
# row whose call sits anywhere else can never run; the sweep closes it instead of
# letting it linger (and, for llm, block admission for the rest of the fleet).
JOB_CALL_STATES: dict[str, tuple[str, ...]] = {
    "asr": ("stored", "transcribing", "failed_retryable", "complete"),
    "correction": ("correcting", "failed_retryable"),
    "emotion": ("emotion_queued", "emotion_analyzing", "failed_retryable"),
    "llm": ("transcribed", "analyzing", "failed_retryable"),
    "notify": ("billed", "notified", "failed_retryable"),
}
TERMINAL_STATES = ("complete", "failed_terminal", "canceled", "missed")


ABANDONED_RESERVATION_AFTER = timedelta(hours=6)


async def release_abandoned_reservations() -> int:
    """Give back credit held by calls whose upload never finished.

    A crash between the reservation commit and the audio store leaves a call in
    ``reserved`` (or ``received``, before the reservation) with no audio; nothing else
    would ever release that hold or move the row out of its state.
    """
    released = 0
    cutoff = datetime.now(UTC) - ABANDONED_RESERVATION_AFTER
    for tenant_id in await routable_tenant_ids():
        try:
            async with session_scope(tenant_id) as session:
                call_ids = (
                    (
                        await session.execute(
                            select(Call.id)
                            .where(
                                Call.tenant_id == tenant_id,
                                # `received` never reaches this sweep otherwise: the upload
                                # died before the audio row, so no worker will ever touch it.
                                Call.status.in_(("received", "reserved")),
                                Call.audio_id.is_(None),
                                Call.created_at < cutoff,
                            )
                            .limit(200)
                            .with_for_update(skip_locked=True)
                        )
                    )
                    .scalars()
                    .all()
                )
                for call_id in call_ids:
                    await billing.release(session, tenant_id=tenant_id, call_id=call_id)
                    call = await session.get(Call, call_id)
                    if call is not None:
                        call.status = "failed_terminal"
                        call.error_code = "ingest_abandoned"
                    released += 1
        except Exception:  # noqa: BLE001 - one tenant must not stop the sweep
            logger.exception(
                "abandoned reservation sweep failed",
                extra={"extra_fields": {"tenant_id": str(tenant_id)}},
            )
    return released


async def settle_stuck_meetings() -> int:
    """Settle finished meetings whose billing failed, and free holds of dead meetings.

    ``meeting_minutes`` swallows a failed settlement so the minutes are still delivered; this
    sweep is the other half of that promise: the customer is charged once, never left held.
    """
    from app.services import meeting_ingest

    fixed = 0
    now = datetime.now(UTC)
    for tenant_id in await routable_tenant_ids():
        try:
            async with session_scope(tenant_id) as session:
                meetings = (
                    (
                        await session.execute(
                            select(Meeting)
                            .where(
                                Meeting.tenant_id == tenant_id,
                                Meeting.updated_at < now - timedelta(minutes=10),
                                ((Meeting.status == "complete") & Meeting.billed_seconds.is_(None))
                                | (
                                    Meeting.status.in_(("canceled", "failed_terminal"))
                                    & (Meeting.updated_at < now - timedelta(hours=24))
                                ),
                            )
                            .limit(100)
                            .with_for_update(skip_locked=True)
                        )
                    )
                    .scalars()
                    .all()
                )
                for meeting in meetings:
                    if meeting.status == "complete":
                        await meeting_ingest.settle_meeting(session, meeting)
                    else:
                        await meeting_ingest.release_meeting(session, meeting)
                    fixed += 1
        except Exception:  # noqa: BLE001 - one tenant must not stop the sweep
            logger.exception(
                "stuck meeting billing sweep failed",
                extra={"extra_fields": {"tenant_id": str(tenant_id)}},
            )
    return fixed


async def expire_abandoned_receivings() -> int:
    """Cancel uploads that stopped arriving, and give back whatever they still hold.

    A meeting whose session was created but never finished keeps its reserved block until it is
    settled; before this sweep nothing released it, so a couple of discarded recordings could
    lock a whole month of a small plan.  `updated_at` moves on every accepted chunk, so a long
    recording that is still uploading is left alone.
    """
    from app.services import meeting_ingest

    cutoff = datetime.now(UTC) - timedelta(hours=get_settings().meeting_abandoned_after_hours)
    expired = 0
    for tenant_id in await routable_tenant_ids():
        try:
            async with session_scope(tenant_id) as session:
                meetings = (
                    (
                        await session.execute(
                            select(Meeting)
                            .where(
                                Meeting.tenant_id == tenant_id,
                                Meeting.status == "receiving",
                                Meeting.updated_at < cutoff,
                            )
                            .limit(100)
                            .with_for_update(skip_locked=True)
                        )
                    )
                    .scalars()
                    .all()
                )
                for meeting in meetings:
                    await meeting_ingest.release_meeting(session, meeting)
                    meeting.status = "canceled"
                    meeting.error_code = "ingest_abandoned"
                    meeting.updated_at = datetime.now(UTC)
                    expired += 1
        except Exception:  # noqa: BLE001 - one tenant must not stop the sweep
            logger.exception(
                "abandoned receiving sweep failed",
                extra={"extra_fields": {"tenant_id": str(tenant_id)}},
            )
    return expired


async def expire_commerce_state() -> tuple[int, int]:
    now = datetime.now(UTC)
    expired_subscriptions = 0
    expired_grants = 0
    # Suspended tenants must lapse too: enforcement alone would leave their rows active forever.
    for tenant_id in await routable_tenant_ids():
        try:
            subscriptions, grants = await _expire_tenant_state(tenant_id, now)
        except Exception:  # noqa: BLE001 - one tenant must not stop the others
            logger.exception(
                "commerce expiry failed", extra={"extra_fields": {"tenant_id": str(tenant_id)}}
            )
            continue
        expired_subscriptions += subscriptions
        expired_grants += grants
    return expired_subscriptions, expired_grants


async def _cancel_stale_orders(
    session: AsyncSession, tenant_id: UUID, now: datetime, ttl_days: int
) -> int:
    """Cancel never-paid draft orders (no payment attempt) older than the configured TTL."""
    cutoff = now - timedelta(days=ttl_days)
    attempted = select(PaymentAttempt.order_id).where(PaymentAttempt.tenant_id == tenant_id)
    orders = (
        (
            await session.execute(
                select(Order)
                .where(
                    Order.tenant_id == tenant_id,
                    Order.status == "draft",
                    Order.created_at < cutoff,
                    Order.id.not_in(attempted),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for order in orders:
        order.status = "canceled"
        changes = (
            (
                await session.execute(
                    select(SubscriptionChange)
                    .where(
                        SubscriptionChange.order_id == order.id,
                        SubscriptionChange.status == "pending_payment",
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for change in changes:
            change.status = "failed"
    return len(orders)


async def _expire_tenant_state(tenant_id: UUID, now: datetime) -> tuple[int, int]:
    expired_subscriptions = 0
    expired_grants = 0
    async with session_scope(tenant_id) as session:
        settings = await get_commerce_settings(session)
        expired_subscriptions = await subscription_state.expire_due(
            session, tenant_id, now, settings.grace_days
        )
        if expired_subscriptions:
            await jalase_accounts.restore_free_plan(session, tenant_id, now)
        await _cancel_stale_orders(session, tenant_id, now, settings.order_ttl_days)

        grants = (
            (
                await session.execute(
                    select(CreditGrant)
                    .where(
                        CreditGrant.expires_at.is_not(None),
                        CreditGrant.expires_at <= now,
                        CreditGrant.remaining_seconds > 0,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for grant in grants:
            amount = grant.remaining_seconds
            cache = await session.get(TenantBalanceCache, grant.tenant_id, with_for_update=True)
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
        try:
            created += await _prepare_tenant_renewals(tenant_id, now)
        except Exception:  # noqa: BLE001 - one tenant must not stop the others
            logger.exception(
                "renewal preparation failed", extra={"extra_fields": {"tenant_id": str(tenant_id)}}
            )
    return created


async def _prepare_tenant_renewals(tenant_id: UUID, now: datetime) -> int:
    created = 0
    async with session_scope(tenant_id) as session:
        settings = await get_commerce_settings(session)
        until = now + timedelta(days=settings.renewal_lead_days)
        subscriptions = (
            (
                await session.execute(
                    select(Subscription).where(
                        Subscription.tenant_id == tenant_id,
                        Subscription.status == "active",
                        Subscription.billing_period.in_(("monthly", "annual")),
                        Subscription.cancel_at_period_end.is_(False),
                        Subscription.period_end > now,
                        Subscription.period_end <= until,
                    )
                )
            )
            .scalars()
            .all()
        )
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
            plan = await session.get(Plan, version.plan_id)
            if plan is None or plan.is_trial or not plan.sellable or not plan.active:
                continue
            if settings.renewal_price_policy == "latest" and not subscription.next_plan_version_id:
                try:
                    _, version = await commerce.plan_version_by_code(session, plan.code)
                except ApiError:
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
            amount, extra_unit = commerce.subscription_amount(version, "annual", extra)
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
                        "billing_period": "annual",
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
            await commerce.apply_tax(session, order, amount, settings.tax_percent)
            created += 1
    return created


def reanalysis_recovery_context(
    call: Call, latest_run: AnalysisRun | None, run_count: int
) -> tuple[bool, str | None]:
    if call.status not in {"transcribed", "analyzing"}:
        return False, None
    metadata = latest_run.result if latest_run is not None and latest_run.result else {}
    tagged = metadata.get("_reanalysis") is True
    legacy = call.status == "analyzing" and "_reanalysis" not in metadata and run_count > 1
    if not (tagged or legacy):
        return False, None
    previous = metadata.get("_previous_status")
    if isinstance(previous, str) and previous:
        return True, previous
    return True, "complete" if call.billed_seconds is not None else "transcribed"


async def run_retention() -> int:
    """Expire audio without removing transcripts or audio still in processing."""
    retired = 0
    for tenant_id in await operational_tenant_ids():
        try:
            # Use independent transactions so a large backlog or a bad tenant cannot stall
            # retention for the rest of the fleet.
            for _ in range(10):
                async with session_scope(tenant_id) as session:
                    batch = await _retire_expired_audio(session, tenant_id)
                retired += batch
                if batch < 100:
                    break
            async with session_scope(tenant_id) as session:
                await session.execute(
                    delete(WebhookDelivery).where(
                        WebhookDelivery.tenant_id == tenant_id,
                        WebhookDelivery.created_at
                        < datetime.now(UTC)
                        - timedelta(days=get_settings().webhook_delivery_retention_days),
                    )
                )
                await speaker_profiles.purge_tombstones(session, tenant_id)
        except Exception:
            logger.warning(
                "Tenant retention failed; check the database and retry",
                extra={"extra_fields": {"tenant_id": str(tenant_id)}},
            )
    return retired


async def _retire_expired_audio(session: AsyncSession, tenant_id: UUID) -> int:
    now = datetime.now(UTC)
    active_since = now - timedelta(days=1)
    active_call = (
        select(Call.id)
        .where(
            Call.audio_id == AudioObject.id,
            Call.status.not_in(("complete", "failed_terminal", "canceled", "missed")),
            Call.updated_at > active_since,
        )
        .exists()
    )
    active_meeting_chunk = (
        select(MeetingChunk.id)
        .join(Meeting, Meeting.id == MeetingChunk.meeting_id)
        .where(
            MeetingChunk.audio_id == AudioObject.id,
            Meeting.status.in_(("receiving", "processing", "failed_retryable")),
            Meeting.updated_at > active_since,
        )
        .exists()
    )
    rows = await session.scalars(
        select(AudioObject)
        .where(
            AudioObject.tenant_id == tenant_id,
            AudioObject.deleted_at.is_(None),
            AudioObject.expires_at < now,
            ~active_call,
            ~active_meeting_chunk,
        )
        .order_by(AudioObject.expires_at, AudioObject.id)
        .limit(100)
        .with_for_update(skip_locked=True)
    )
    batch = rows.all()
    for audio in batch:
        await audio_lifecycle.retire_audio(session, audio)
    return len(batch)


async def _latest_job(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, kind: str
) -> Job | None:
    return (
        await session.execute(
            select(Job)
            .where(Job.tenant_id == tenant_id, Job.call_id == call_id, Job.kind == kind)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _pending_outbox(session: AsyncSession, job_id: UUID) -> bool:
    """A staged, not-yet-dispatched outbox row already owns this delivery.

    The reconciler used to stage a fresh row on every pass, which burst through
    the deliberate notify delay and grew `job_outbox` without bound.
    """
    return (
        await session.scalar(
            select(JobOutbox.id)
            .where(JobOutbox.job_id == job_id, JobOutbox.dispatched_at.is_(None))
            .limit(1)
        )
    ) is not None


async def _recovery_extras(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call: Call,
    kind: str,
    reanalysis: bool,
    previous_status: str | None,
) -> dict[str, object] | None:
    """Payload fields needed to re-dispatch a stuck job, or None when it cannot run."""
    extras: dict[str, object] = {
        "analysis_run_id": None,
        "correction_run_id": None,
        "asr_revision_id": None,
        "retranscription": False,
        "reanalysis": reanalysis,
        "previous_status": previous_status,
        "event": None,
    }
    if kind == "asr":
        revision = await session.scalar(
            select(AsrTranscriptRevision)
            .where(
                AsrTranscriptRevision.call_id == call.id,
                AsrTranscriptRevision.tenant_id == tenant_id,
                AsrTranscriptRevision.status.in_(("queued", "running")),
            )
            .order_by(AsrTranscriptRevision.created_at.desc())
            .limit(1)
        )
        if revision is not None:
            extras["asr_revision_id"] = revision.id
            extras["retranscription"] = True
            extras["previous_status"] = str(
                (revision.metrics or {}).get("previous_status") or "complete"
            )
        elif call.status not in ("stored", "transcribing", "failed_retryable"):
            return None
    elif kind == "correction":
        revision = await session.scalar(
            select(TranscriptRevision)
            .where(
                TranscriptRevision.call_id == call.id,
                TranscriptRevision.tenant_id == tenant_id,
                TranscriptRevision.status.in_(("queued", "running", "validating", "succeeded")),
            )
            .order_by(TranscriptRevision.created_at.desc())
            .limit(1)
        )
        if revision is None:
            return None
        extras["correction_run_id"] = revision.id
    elif kind == "emotion":
        run_id = await session.scalar(
            select(AnalysisRun.id)
            .where(AnalysisRun.call_id == call.id, AnalysisRun.tenant_id == tenant_id)
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
        )
        if run_id is None:
            return None
        extras["analysis_run_id"] = run_id
    elif kind == "notify":
        extras["event"] = "call.complete"
    return extras


async def _fail_call(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call: Call,
    error_code: str,
    detail: str,
) -> None:
    """Stop a call that can no longer advance, release its hold and notify the tenant."""
    call.status = "failed_terminal"
    call.error_code = error_code
    call.progress_detail = detail[:500]
    call.updated_at = datetime.now(UTC)
    await billing.release(session, tenant_id=tenant_id, call_id=call.id)
    await outbox.stage(
        session,
        tenant_id=tenant_id,
        queue_name="q:notify",
        function_name="deliver_event",
        payload={
            "tenant_id": str(tenant_id),
            "call_id": str(call.id),
            "event": "call.failed",
        },
    )


async def _close_queued_duplicates(
    session: AsyncSession, *, tenant_id: UUID, call: Call, kind: str
) -> int:
    """Close redundant queued rows so a stale duplicate cannot block admission."""
    closed = await pipeline.close_queued_duplicates(
        session, tenant_id=tenant_id, call_id=call.id, kind=kind
    )
    if closed:
        logger.warning(
            "closed duplicate queued jobs",
            extra={
                "extra_fields": {
                    "call_id": str(call.id),
                    "kind": kind,
                    "closed": closed,
                    "error_code": "job_superseded",
                }
            },
        )
    return closed


async def _settle_after_terminal_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call: Call,
    kind: str,
    error_code: str | None,
) -> None:
    """Move a call out of a state whose step has permanently given up.

    Notification is best-effort: the analysis is done and billed, so the call is
    complete even when the webhook never accepts the event. Every other stage is on
    the path to a result, so the call cannot finish and is stopped with the job's code.
    """
    if kind == "notify" and call.status in ("billed", "notified"):
        call.status = "complete"
        call.error_code = None
        values = progress.values_for_status("complete")
        call.progress_pct = int(values["progress_pct"])
        call.progress_detail = str(values["progress_detail"])
        call.updated_at = datetime.now(UTC)
        return
    await _fail_call(
        session,
        tenant_id=tenant_id,
        call=call,
        error_code=error_code or "job_call_state_mismatch",
        detail="مرحله پردازش پس از چند تلاش متوقف شد؛ تماس ادامه پیدا نکرد. دوباره پردازش کنید.",
    )


async def _recover_call(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call: Call,
    kind: str,
    reanalysis: bool,
    previous_status: str | None,
    running_cutoff: datetime,
) -> tuple[UUID | None, bool]:
    """Re-dispatch or close one call stage; the flag marks a real anomaly.

    A routine re-dispatch of a queued job (worker saturated) is not an anomaly and
    must not count towards ``cbi_calls_stuck`` or its alert.
    """
    # Lock the job row, in the same order the workers use (job, then call), and
    # re-check its state: the sweep read the call before another worker could claim.
    job = (
        await session.execute(
            select(Job)
            .where(Job.tenant_id == tenant_id, Job.call_id == call.id, Job.kind == kind)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is not None:
        if job.status in {"failed_terminal", "canceled"}:
            # The stage gave up for good. Re-dispatching it here retried forever (and for
            # notify, burned a delivery every 30 s); settle the call the way the stage's
            # own terminal path should have instead.
            closed = await _close_queued_duplicates(
                session, tenant_id=tenant_id, call=call, kind=kind
            )
            settled = call.status not in TERMINAL_STATES
            if settled:
                await _settle_after_terminal_job(
                    session,
                    tenant_id=tenant_id,
                    call=call,
                    kind=kind,
                    error_code=job.error_code,
                )
            return None, bool(closed) or settled
        if job.status == "succeeded" and kind != "correction":
            # Success commits the call's next state in the same transaction; a
            # succeeded row on a stuck call is a leftover, not a missing hand-off.
            # Correction is different: it commits the revision, then stages the
            # analysis in a second transaction, so its hand-off can be lost.
            closed = await _close_queued_duplicates(
                session, tenant_id=tenant_id, call=call, kind=kind
            )
            return None, bool(closed)
        if job.status == "running":
            heartbeats = [value for value in (job.locked_at, job.started_at) if value]
            heartbeats.append(call.updated_at)
            if max(heartbeats) >= running_cutoff:
                # An older queued duplicate is still the global admission candidate.
                closed = await _close_queued_duplicates(
                    session, tenant_id=tenant_id, call=call, kind=kind
                )
                return None, bool(closed)
        # Re-check under the row lock: two overlapping sweeps must not stage two
        # deliveries for the same job.
        if await _pending_outbox(session, job.id):
            return None, False
    extras = await _recovery_extras(
        session,
        tenant_id=tenant_id,
        call=call,
        kind=kind,
        reanalysis=reanalysis,
        previous_status=previous_status,
    )
    if extras is None:
        # Nothing to dispatch: close the row and, when the call is still processing,
        # stop it instead of leaving a state no worker will ever revisit.
        closed = False
        if job is not None:
            closed = await pipeline.close_unclaimable_job(session, job)
        if call.status not in TERMINAL_STATES:
            await _fail_call(
                session,
                tenant_id=tenant_id,
                call=call,
                error_code="job_call_state_mismatch",
                detail="مرحله بعدی پردازش قابل بازیابی نبود؛ تماس متوقف شد. دوباره پردازش کنید.",
            )
            closed = True
        return None, closed
    # One active job per call/kind is enforced by a partial unique index; close older
    # queued rows before moving the newest back to queued, or the UPDATE fails.
    await _close_queued_duplicates(session, tenant_id=tenant_id, call=call, kind=kind)
    job = await pipeline.mark_job(
        session, tenant_id=tenant_id, call_id=call.id, kind=kind, status="queued"
    )
    if job is None:
        return None, False
    staged = await outbox.stage_job(
        session,
        job_id=job.id,
        tenant_id=tenant_id,
        call_id=call.id,
        kind=kind,
        recovery=True,
        **extras,  # type: ignore[arg-type]
    )
    return staged, False


async def _redispatch_lost_retries(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    now: datetime,
    stale_before: datetime,
) -> tuple[list[UUID], dict[str, int]]:
    """Re-arm a retry whose ARQ delivery was lost after the outbox marked it sent.

    ``handle_failure`` stages an outbox row and marks it dispatched once ARQ accepts
    the enqueue. If that ARQ job is then lost (Redis restart without persistence, an
    evicted key, a worker killed before the claim), the job stays ``failed_retryable``
    with no undispatched row, and no sweep looked at it: the call waited for the 72 h
    watchdog instead of retrying. ARQ dedupes on the job id, so re-arming the same row
    is a no-op; the original payload is cloned into a new row instead.
    """
    staged: list[UUID] = []
    anomalies: dict[str, int] = {}
    jobs = (
        (
            await session.execute(
                select(Job)
                .where(
                    Job.tenant_id == tenant_id,
                    Job.status == "failed_retryable",
                    Job.run_after.is_not(None),
                    Job.run_after < stale_before,
                )
                .order_by(Job.run_after, Job.id)
                .with_for_update(skip_locked=True)
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    for job in jobs:
        newest = await _latest_job(session, tenant_id=tenant_id, call_id=job.call_id, kind=job.kind)
        if newest is not None and newest.id != job.id:
            # A newer attempt already owns this stage; this row is an obsolete retry.
            closed = await pipeline.close_unclaimable_job(
                session,
                job,
                error_code="job_superseded",
                statuses=("failed_retryable",),
            )
            if closed:
                anomalies[job.kind] = anomalies.get(job.kind, 0) + 1
            continue
        call = await session.get(Call, job.call_id)
        if call is None:
            continue
        if call.status not in JOB_CALL_STATES[job.kind]:
            closed = await pipeline.close_unclaimable_job(
                session, job, statuses=("failed_retryable",)
            )
            if closed:
                anomalies[job.kind] = anomalies.get(job.kind, 0) + 1
            continue
        if await _pending_outbox(session, job.id):
            # The delivery is still pending; the dispatcher owns it.
            continue
        previous = await session.scalar(
            select(JobOutbox)
            .where(JobOutbox.job_id == job.id, JobOutbox.dispatched_at.is_not(None))
            .order_by(JobOutbox.created_at.desc(), JobOutbox.id.desc())
            .limit(1)
        )
        if previous is None:
            # No delivery was ever sent, so there is nothing to replay.
            continue
        last_sent = previous.dispatched_at
        if last_sent is None or last_sent >= stale_before:
            # The last delivery is recent enough that the worker may still be
            # claiming it; the next sweep decides.
            continue
        outbox_id = await outbox.stage(
            session,
            tenant_id=tenant_id,
            job_id=job.id,
            queue_name=previous.queue_name,
            function_name=previous.function_name,
            payload=dict(previous.payload),
            available_at=now,
        )
        job.run_after = now
        staged.append(outbox_id)
        anomalies[job.kind] = anomalies.get(job.kind, 0) + 1
    if staged:
        logger.warning(
            "re-armed retries whose worker delivery was lost",
            extra={"extra_fields": {"tenant_id": str(tenant_id), "count": len(staged)}},
        )
    return staged, anomalies


async def _reconcile_tenant(
    tenant_id: UUID,
    *,
    now: datetime,
    queued_cutoff: datetime,
    running_cutoff: datetime,
) -> tuple[int, dict[str, int]]:
    outbox_ids: list[UUID] = []
    requeued = 0
    counts: dict[str, int] = {}
    async with session_scope(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(Call)
                    .where(
                        (Call.status.in_(tuple(QUEUED_STATES)) & (Call.updated_at < queued_cutoff))
                        | (
                            Call.status.in_(tuple(RUNNING_STATES))
                            & (Call.updated_at < running_cutoff)
                        )
                    )
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        call_ids = [call.id for call in rows]
        run_counts: dict[UUID, int] = {}
        latest_runs: dict[UUID, AnalysisRun] = {}
        if call_ids:
            for call_id, count in (
                await session.execute(
                    select(AnalysisRun.call_id, func.count(AnalysisRun.id))
                    .where(AnalysisRun.call_id.in_(call_ids))
                    .group_by(AnalysisRun.call_id)
                )
            ).all():
                run_counts[call_id] = count
            for run in (
                (
                    await session.execute(
                        select(AnalysisRun)
                        .where(AnalysisRun.call_id.in_(call_ids))
                        .order_by(AnalysisRun.call_id, AnalysisRun.created_at.desc())
                    )
                )
                .scalars()
                .all()
            ):
                latest_runs.setdefault(run.call_id, run)
        handled: set[tuple[UUID, str]] = set()
        for call in rows:
            kind = IN_FLIGHT[call.status]
            job = await _latest_job(session, tenant_id=tenant_id, call_id=call.id, kind=kind)
            if call.status in RUNNING_STATES and job is not None and job.status == "running":
                heartbeats = [value for value in (job.locked_at, job.started_at) if value]
                heartbeats.append(call.updated_at)
                if max(heartbeats) >= running_cutoff:
                    continue
            if (
                job is not None
                and job.status == "queued"
                and await _pending_outbox(session, job.id)
            ):
                continue
            reanalysis, previous_status = reanalysis_recovery_context(
                call, latest_runs.get(call.id), int(run_counts.get(call.id, 0))
            )
            handled.add((call.id, kind))
            staged, anomaly = await _recover_call(
                session,
                tenant_id=tenant_id,
                call=call,
                kind=kind,
                reanalysis=reanalysis,
                previous_status=previous_status,
                running_cutoff=running_cutoff,
            )
            if anomaly:
                counts[kind] = counts.get(kind, 0) + 1
            if staged is not None:
                outbox_ids.append(staged)
                requeued += 1

        # Job-driven sweep: a queued row whose call is not in a recovered status was
        # invisible to the call-driven pass (lost retranscription/notify outboxes).
        queued_jobs = (
            (
                await session.execute(
                    select(Job)
                    .where(
                        Job.status == "queued",
                        Job.queued_at < queued_cutoff,
                        Job.kind.in_(tuple(JOB_CALL_STATES)),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        for job in queued_jobs:
            if (job.call_id, job.kind) in handled:
                continue
            queued_call = await session.get(Call, job.call_id)
            if queued_call is None or await _pending_outbox(session, job.id):
                continue
            handled.add((queued_call.id, job.kind))
            if queued_call.status not in JOB_CALL_STATES[job.kind]:
                if await pipeline.close_unclaimable_job(session, job):
                    counts[job.kind] = counts.get(job.kind, 0) + 1
                continue
            latest_run = (
                await session.scalar(
                    select(AnalysisRun)
                    .where(
                        AnalysisRun.call_id == queued_call.id,
                        AnalysisRun.tenant_id == tenant_id,
                    )
                    .order_by(AnalysisRun.created_at.desc())
                    .limit(1)
                )
                if job.kind == "llm"
                else None
            )
            reanalysis, previous_status = reanalysis_recovery_context(queued_call, latest_run, 1)
            staged, anomaly = await _recover_call(
                session,
                tenant_id=tenant_id,
                call=queued_call,
                kind=job.kind,
                reanalysis=reanalysis,
                previous_status=previous_status,
                running_cutoff=running_cutoff,
            )
            if anomaly:
                counts[job.kind] = counts.get(job.kind, 0) + 1
            if staged is not None:
                outbox_ids.append(staged)
                requeued += 1

        # Last-resort watchdog: no non-terminal call may keep a reservation forever.
        timeout_cutoff = now - timedelta(hours=get_settings().call_stuck_timeout_hours)
        stale_calls = (
            (
                await session.execute(
                    select(Call)
                    .where(
                        Call.status.not_in(TERMINAL_STATES + ("received", "reserved")),
                        Call.updated_at < timeout_cutoff,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        for call in stale_calls:
            await _fail_call(
                session,
                tenant_id=tenant_id,
                call=call,
                error_code="processing_timeout",
                detail="مهلت مجاز پردازش تمام شد؛ پردازش متوقف شد. دوباره تلاش کنید.",
            )
            counts["timeout"] = counts.get("timeout", 0) + 1

        # A retry whose ARQ delivery vanished after the outbox marked it sent used to
        # wait for that watchdog; replay it from its own recorded payload instead.
        # Runs after the watchdog so a call it just stopped does not get a delivery.
        lost_ids, lost = await _redispatch_lost_retries(
            session, tenant_id=tenant_id, now=now, stale_before=queued_cutoff
        )
        outbox_ids.extend(lost_ids)
        requeued += len(lost_ids)
        for kind, value in lost.items():
            counts[kind] = counts.get(kind, 0) + value

    for outbox_id in outbox_ids:
        try:
            await outbox.dispatch_one(outbox_id, tenant_id)
        except Exception:  # noqa: BLE001 - the dispatcher retries; keep the sweep running
            logger.exception(
                "recovery dispatch failed",
                extra={"extra_fields": {"tenant_id": str(tenant_id)}},
            )
    return requeued, counts


async def reconcile_stuck_calls() -> int:
    """§6 reconciler: re-enqueue rows that stalled between a commit and an ARQ enqueue.

    Every non-terminal call is covered: queued and running stages, corrections, and
    queued job rows whose call already moved on (closed as orphans). One bad tenant
    must never stop the sweep for the rest.
    """
    now = datetime.now(UTC)
    queued_cutoff = now - STUCK_AFTER
    running_cutoff = now - RUNNING_STUCK_AFTER
    requeued = 0
    totals: dict[str, int] = {}
    for tenant_id in await operational_tenant_ids():
        try:
            count, counts = await _reconcile_tenant(
                tenant_id,
                now=now,
                queued_cutoff=queued_cutoff,
                running_cutoff=running_cutoff,
            )
        except Exception:  # noqa: BLE001 - one tenant must not stop the fleet sweep
            logger.exception(
                "stuck-call sweep failed",
                extra={"extra_fields": {"tenant_id": str(tenant_id)}},
            )
            continue
        requeued += count
        for kind, value in counts.items():
            totals[kind] = totals.get(kind, 0) + value
    for kind in (*JOB_CALL_STATES, "timeout"):
        calls_stuck.labels(kind=kind).set(totals.get(kind, 0))
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
    for name in (
        queue.QUEUE_ASR,
        queue.QUEUE_EMOTION,
        queue.QUEUE_LLM,
        queue.QUEUE_ASSISTANT,
        queue.QUEUE_NOTIFY,
    ):
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
