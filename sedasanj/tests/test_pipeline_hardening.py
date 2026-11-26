"""Regression tests for call-pipeline stalls and the reconciler's full coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from tests.plan_helpers import requires_postgres, scratch  # noqa: F401

from app.services import maintenance, pipeline


def test_every_reconciled_status_has_a_job_mapping() -> None:
    for status, kind in {**maintenance.QUEUED_STATES, **maintenance.RUNNING_STATES}.items():
        assert status in maintenance.JOB_CALL_STATES[kind], (
            f"{status} maps to {kind} but is not a claimable call state for it"
        )


def test_correcting_and_correction_are_covered() -> None:
    assert maintenance.QUEUED_STATES["correcting"] == "correction"
    assert "correcting" in maintenance.JOB_CALL_STATES["correction"]


def test_llm_gate_accepts_the_states_the_worker_claims() -> None:
    assert set(pipeline.LLM_CLAIMABLE_CALL_STATES) == {
        "transcribed",
        "analyzing",
        "failed_retryable",
    }


async def test_close_unclaimable_only_closes_queued_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []

    async def record(_session: Any, **kwargs: Any) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(pipeline.processing_events, "record", record)
    queued = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        call_id=uuid4(),
        kind="llm",
        status="queued",
        error_code=None,
        error_detail=None,
        completed_at=None,
    )
    running = SimpleNamespace(**{**vars(queued), "id": uuid4(), "status": "running"})
    assert await pipeline.close_unclaimable_job(None, queued) is True  # type: ignore[arg-type]
    assert queued.status == "failed_terminal"
    assert queued.error_code == "job_call_state_mismatch"
    assert await pipeline.close_unclaimable_job(None, running) is False  # type: ignore[arg-type]
    assert running.status == "running"
    assert recorded and recorded[0]["call_id"] == queued.call_id


async def test_handle_cancellation_records_a_retryable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def handle_failure(**kwargs: Any) -> bool:
        captured.update(kwargs)
        return True

    monkeypatch.setattr(pipeline, "handle_failure", handle_failure)
    tenant_id, call_id = uuid4(), uuid4()
    await pipeline.handle_cancellation(
        tenant_id=tenant_id,
        call_id=call_id,
        kind="llm",
        reanalysis=False,
    )
    assert captured["error_code"] == "job_cancelled"
    assert captured["retryable"] is True
    assert captured["tenant_id"] == tenant_id
    assert captured["call_id"] == call_id


# --- Database-backed reconciler tests ---------------------------------------------


async def _tenant_and_call(
    *,
    status: str,
    updated_at: datetime,
    with_job: str | None = None,
    job_status: str = "queued",
    queued_at: datetime | None = None,
    run_after: datetime | None = None,
) -> tuple[UUID, UUID, UUID | None]:
    from app import db
    from app.models import Call, Job, Tenant

    tenant_id, call_id, job_id = uuid4(), uuid4(), None
    async with db.session_scope(None, staff=True) as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"stall-{uuid4().hex[:6]}",
                price_per_minute_toman=2000,
            )
        )
        await session.flush()
        session.add(
            Call(
                id=call_id,
                tenant_id=tenant_id,
                asterisk_uniqueid=f"uid-{call_id}",
                call_type="answered",
                started_at=updated_at - timedelta(minutes=2),
                ended_at=updated_at,
                duration_ms=120_000,
                status=status,
                updated_at=updated_at,
            )
        )
        if with_job is not None:
            job = Job(
                tenant_id=tenant_id,
                call_id=call_id,
                kind=with_job,
                status=job_status,
                attempt=0,
            )
            session.add(job)
            await session.flush()
            if queued_at is not None:
                job.queued_at = queued_at
            if run_after is not None:
                job.run_after = run_after
            job_id = job.id
    return tenant_id, call_id, job_id


async def _cleanup(tenant_id: UUID) -> None:
    from sqlalchemy import delete

    from app import db
    from app.models import Call, Job, JobOutbox, Tenant

    async with db.session_scope(None, staff=True) as session:
        await session.execute(delete(JobOutbox).where(JobOutbox.tenant_id == tenant_id))
        await session.execute(delete(Job).where(Job.tenant_id == tenant_id))
        await session.execute(delete(Call).where(Call.tenant_id == tenant_id))
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_reconciler_closes_orphan_job_and_recovers_claimable_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import func, select

    from app import db
    from app.models import Call, Job, JobOutbox

    dispatched: list[Any] = []

    async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
        dispatched.append(outbox_id)
        return True

    monkeypatch.setattr(maintenance.outbox, "dispatch_one", dispatch_one)
    now = datetime.now(UTC)
    old = now - timedelta(minutes=5)
    orphan_tenant, orphan_call, orphan_job = await _tenant_and_call(
        status="complete", updated_at=old, with_job="llm", queued_at=old
    )
    live_tenant, live_call, live_job = await _tenant_and_call(
        status="transcribed", updated_at=old, with_job="llm", queued_at=old
    )
    try:
        assert await maintenance.reconcile_stuck_calls() >= 1
        async with db.session_scope(None, staff=True) as session:
            orphan = await session.get(Job, orphan_job)
            live = await session.get(Job, live_job)
            assert orphan is not None and orphan.status == "failed_terminal"
            assert orphan.error_code == "job_call_state_mismatch"
            assert live is not None and live.status == "queued"
            staged = await session.scalar(
                select(func.count(JobOutbox.id)).where(
                    JobOutbox.tenant_id == live_tenant, JobOutbox.job_id == live_job
                )
            )
            assert staged == 1
            call = await session.get(Call, live_call)
            assert call is not None
    finally:
        await _cleanup(orphan_tenant)
        await _cleanup(live_tenant)


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_reconciler_closes_a_duplicate_and_stops_the_call_whose_step_gave_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import select

    from app import db
    from app.models import Call, Job

    async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
        return True

    monkeypatch.setattr(maintenance.outbox, "dispatch_one", dispatch_one)
    old = datetime.now(UTC) - timedelta(minutes=5)
    tenant_id, call_id, _job = await _tenant_and_call(status="transcribed", updated_at=old)
    async with db.session_scope(None, staff=True) as session:
        duplicate = Job(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            status="queued",
            attempt=0,
            queued_at=old,
            created_at=old,
        )
        session.add(duplicate)
        await session.flush()
        newest = Job(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="llm",
            status="failed_terminal",
            attempt=1,
            error_code="llm_provider_task_failed",
            created_at=old + timedelta(minutes=1),
        )
        session.add(newest)
        await session.flush()
        duplicate_id, newest_id = duplicate.id, newest.id
    try:
        await maintenance.reconcile_stuck_calls()
        async with db.session_scope(None, staff=True) as session:
            duplicate = await session.get(Job, duplicate_id)
            newest = await session.get(Job, newest_id)
            assert duplicate is not None and duplicate.status == "failed_terminal"
            assert duplicate.error_code == "job_superseded"
            # Re-dispatching a terminal row retried it forever; the call is stopped instead.
            assert newest is not None and newest.status == "failed_terminal"
            active = await session.scalar(
                select(Job.id).where(
                    Job.tenant_id == tenant_id,
                    Job.call_id == call_id,
                    Job.status.in_(("queued", "running")),
                )
            )
            assert active is None
            call = await session.get(Call, call_id)
            assert call is not None and call.status == "failed_terminal"
            assert call.error_code == "llm_provider_task_failed"
    finally:
        await _cleanup(tenant_id)


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_reconciler_completes_a_call_whose_notification_gave_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A webhook nobody accepts is best-effort; the analysed call must not stay billed."""
    from app import db
    from app.models import Call

    async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
        return True

    monkeypatch.setattr(maintenance.outbox, "dispatch_one", dispatch_one)
    old = datetime.now(UTC) - timedelta(minutes=5)
    tenant_id, call_id, _job = await _tenant_and_call(
        status="billed",
        updated_at=old,
        with_job="notify",
        job_status="failed_terminal",
        queued_at=old,
    )
    try:
        await maintenance.reconcile_stuck_calls()
        async with db.session_scope(None, staff=True) as session:
            call = await session.get(Call, call_id)
            assert call is not None
            assert call.status == "complete"
            assert call.error_code is None
    finally:
        await _cleanup(tenant_id)


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_reconciler_does_not_burst_the_delayed_notify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import func, select

    from app import db
    from app.models import JobOutbox

    async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
        raise AssertionError("a pending delayed outbox must not be dispatched again")

    monkeypatch.setattr(maintenance.outbox, "dispatch_one", dispatch_one)
    now = datetime.now(UTC)
    old = now - timedelta(minutes=5)
    tenant_id, call_id, job_id = await _tenant_and_call(
        status="billed", updated_at=old, with_job="notify", queued_at=old
    )
    async with db.session_scope(None, staff=True) as session:
        session.add(
            JobOutbox(
                tenant_id=tenant_id,
                job_id=job_id,
                queue_name="q:notify",
                function_name="deliver_event",
                payload={
                    "tenant_id": str(tenant_id),
                    "call_id": str(call_id),
                    "event": "call.complete",
                },
                available_at=now + timedelta(minutes=55),
            )
        )
    try:
        await maintenance.reconcile_stuck_calls()
        async with db.session_scope(None, staff=True) as session:
            total = await session.scalar(
                select(func.count(JobOutbox.id)).where(JobOutbox.tenant_id == tenant_id)
            )
            assert total == 1
    finally:
        await _cleanup(tenant_id)


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_reconciler_stops_a_call_with_no_recoverable_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import db
    from app.models import Call

    async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
        return True

    monkeypatch.setattr(maintenance.outbox, "dispatch_one", dispatch_one)
    now = datetime.now(UTC)
    old = now - timedelta(minutes=5)
    tenant_id, call_id, _job = await _tenant_and_call(
        status="correcting", updated_at=old, with_job="correction", queued_at=old
    )
    try:
        await maintenance.reconcile_stuck_calls()
        async with db.session_scope(None, staff=True) as session:
            call = await session.get(Call, call_id)
            assert call is not None
            assert call.status == "failed_terminal"
            assert call.error_code == "job_call_state_mismatch"
    finally:
        await _cleanup(tenant_id)


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_reconciler_times_out_an_ancient_processing_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import db
    from app.models import Call

    async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
        return True

    monkeypatch.setattr(maintenance.outbox, "dispatch_one", dispatch_one)
    ancient = datetime.now(UTC) - timedelta(days=10)
    tenant_id, call_id, _job = await _tenant_and_call(status="transcribing", updated_at=ancient)
    try:
        await maintenance.reconcile_stuck_calls()
        async with db.session_scope(None, staff=True) as session:
            call = await session.get(Call, call_id)
            assert call is not None
            assert call.status == "failed_terminal"
            assert call.error_code == "processing_timeout"
    finally:
        await _cleanup(tenant_id)


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_mark_job_returns_none_when_the_call_was_deleted() -> None:
    """A worker outliving ``DELETE /calls/{id}`` must not break its transaction on the FK."""
    from app import db
    from app.models import Call

    tenant_id, call_id, _job = await _tenant_and_call(
        status="transcribed", updated_at=datetime.now(UTC)
    )
    try:
        async with db.session_scope(None, staff=True) as session:
            call = await session.get(Call, call_id)
            assert call is not None
            await session.delete(call)
        async with db.session_scope(None, staff=True) as session:
            job = await pipeline.mark_job(
                session, tenant_id=tenant_id, call_id=call_id, kind="llm", status="failed_terminal"
            )
            assert job is None
    finally:
        await _cleanup(tenant_id)


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_recovery_flag_separates_a_redispatch_from_a_real_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Saturation re-dispatch feeds returns, not the stuck-call metric."""
    from app import db
    from app.models import Call

    async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
        return True

    monkeypatch.setattr(maintenance.outbox, "dispatch_one", dispatch_one)
    old = datetime.now(UTC) - timedelta(minutes=5)
    running_cutoff = datetime.now(UTC) - maintenance.RUNNING_STUCK_AFTER
    healthy_tenant, healthy_call, _ = await _tenant_and_call(
        status="transcribed", updated_at=old, with_job="llm", queued_at=old
    )
    broken_tenant, broken_call, _ = await _tenant_and_call(
        status="correcting", updated_at=old, with_job="correction", queued_at=old
    )
    try:
        async with db.session_scope(None, staff=True) as session:
            call = await session.get(Call, healthy_call)
            assert call is not None
            staged, anomaly = await maintenance._recover_call(
                session,
                tenant_id=healthy_tenant,
                call=call,
                kind="llm",
                reanalysis=False,
                previous_status=None,
                running_cutoff=running_cutoff,
            )
            assert staged is not None
            assert anomaly is False
        async with db.session_scope(None, staff=True) as session:
            call = await session.get(Call, broken_call)
            assert call is not None
            # No revision exists, so the correction cannot be re-dispatched: that is
            # the case the sweep must count (and alert on).
            staged, anomaly = await maintenance._recover_call(
                session,
                tenant_id=broken_tenant,
                call=call,
                kind="correction",
                reanalysis=False,
                previous_status=None,
                running_cutoff=running_cutoff,
            )
            assert staged is None
            assert anomaly is True
    finally:
        await _cleanup(healthy_tenant)
        await _cleanup(broken_tenant)


@requires_postgres
@pytest.mark.usefixtures("scratch")
async def test_reconciler_rearms_a_retry_whose_delivery_was_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dispatched-but-lost retry used to wait for the 72 h watchdog."""
    from sqlalchemy import select

    from app import db
    from app.models import Call, JobOutbox

    async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
        return True

    monkeypatch.setattr(maintenance.outbox, "dispatch_one", dispatch_one)
    old = datetime.now(UTC) - timedelta(minutes=10)
    tenant_id, call_id, job_id = await _tenant_and_call(
        status="failed_retryable",
        updated_at=old,
        with_job="llm",
        job_status="failed_retryable",
        queued_at=old,
        run_after=old,
    )
    payload = {
        "tenant_id": str(tenant_id),
        "call_id": str(call_id),
        "analysis_run_id": str(uuid4()),
    }
    async with db.session_scope(None, staff=True) as session:
        session.add(
            JobOutbox(
                tenant_id=tenant_id,
                job_id=job_id,
                queue_name="q:llm",
                function_name="analyze_call",
                payload=payload,
                available_at=old,
                dispatched_at=old,
            )
        )
    try:
        await maintenance.reconcile_stuck_calls()
        async with db.session_scope(None, staff=True) as session:
            rows = (
                (
                    await session.execute(
                        select(JobOutbox)
                        .where(JobOutbox.tenant_id == tenant_id, JobOutbox.job_id == job_id)
                        .order_by(JobOutbox.created_at, JobOutbox.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 2
            rearmed = rows[-1]
            assert rearmed.dispatched_at is None
            assert rearmed.queue_name == "q:llm"
            assert rearmed.function_name == "analyze_call"
            assert rearmed.payload == payload
            call = await session.get(Call, call_id)
            assert call is not None and call.status == "failed_retryable"
    finally:
        await _cleanup(tenant_id)
