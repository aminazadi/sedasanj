from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models import AnalysisRun, Call, Job
from app.services import pipeline, queue
from app.services.maintenance import (
    RUNNING_STUCK_AFTER,
    STUCK_AFTER,
    reanalysis_recovery_context,
)
from app.services.pipeline import RETRY_POLICY, backoff_for
from worker_llm.main import (
    _claimable_call_statuses,
    _claimable_job_statuses,
    _status_after_successful_reanalysis,
)


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


def test_retry_policy_matches_the_plan() -> None:
    assert RETRY_POLICY["asr"] == (5, 5, 2)
    assert RETRY_POLICY["emotion"] == (3, 10, 2)
    assert RETRY_POLICY["llm"] == (4, 10, 2)
    assert RETRY_POLICY["notify"] == (8, 15, 2)


@pytest.mark.parametrize(
    ("kind", "attempt", "seconds"),
    [
        ("asr", 0, 5),
        ("asr", 3, 40),
        ("llm", 0, 10),
        ("llm", 2, 40),
        ("notify", 1, 30),
    ],
)
def test_backoff_grows_exponentially(kind: str, attempt: int, seconds: int) -> None:
    assert backoff_for(kind, attempt) == timedelta(seconds=seconds)


def test_running_jobs_are_not_reconciled_before_the_worker_timeout() -> None:
    assert timedelta(seconds=30) == STUCK_AFTER
    assert timedelta(minutes=35) < RUNNING_STUCK_AFTER


def test_normal_reanalysis_claims_the_api_in_progress_state_once_job_is_owned() -> None:
    assert "analyzing" in _claimable_call_statuses(reanalysis=True, recovery=False)
    assert "running" not in _claimable_job_statuses(recovery=False)


def test_recovery_can_reclaim_a_stale_running_job() -> None:
    assert "analyzing" in _claimable_call_statuses(reanalysis=True, recovery=True)
    assert "running" in _claimable_job_statuses(recovery=True)


def test_reanalysis_recovery_uses_persisted_previous_status() -> None:
    call = Call(status="analyzing", billed_seconds=120)
    run = AnalysisRun(result={"_reanalysis": True, "_previous_status": "failed_terminal"})

    assert reanalysis_recovery_context(call, run, 2) == (True, "failed_terminal")


def test_initial_analysis_is_not_mistaken_for_reanalysis() -> None:
    call = Call(status="analyzing", billed_seconds=None)
    run = AnalysisRun(result=None)

    assert reanalysis_recovery_context(call, run, 1) == (False, None)


@pytest.mark.parametrize(
    ("previous_status", "expected"),
    [
        ("complete", "complete"),
        ("billed", "billed"),
        ("failed_retryable", "complete"),
        ("failed_terminal", "complete"),
        (None, "complete"),
    ],
)
def test_successful_reanalysis_clears_a_previous_failure(
    previous_status: str | None, expected: str
) -> None:
    assert _status_after_successful_reanalysis(previous_status) == expected


@pytest.mark.asyncio
async def test_recovery_flag_is_carried_in_llm_queue_payload() -> None:
    memory = queue.MemoryQueue()
    queue.set_queue(memory)
    try:
        await queue.enqueue_llm(uuid4(), None, recovery=True, job_id="recovery-test")
    finally:
        queue.set_queue(None)

    assert memory.jobs[0][2]["recovery"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected", "claimable"),
    [
        ("queued", ("queued", "failed_retryable"), True),
        ("failed_retryable", ("queued", "failed_retryable"), True),
        ("running", ("queued", "failed_retryable"), False),
        ("running", ("queued", "failed_retryable", "running"), True),
    ],
)
async def test_job_claim_requires_an_expected_locked_state(
    status: str, expected: tuple[str, ...], claimable: bool
) -> None:
    job = Job(
        tenant_id=uuid4(),
        call_id=uuid4(),
        kind="llm",
        status=status,
        attempt=0,
        run_after=datetime.now(UTC),
    )
    session = type("Session", (), {"execute": AsyncMock(return_value=_ScalarResult(job))})()

    claimed = await pipeline.lock_job_for_claim(
        session,
        tenant_id=job.tenant_id,
        call_id=job.call_id,
        kind="llm",
        expected=expected,
    )

    assert (claimed is job) is claimable


@pytest.mark.asyncio
async def test_reanalysis_retry_preserves_previous_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    call_id = uuid4()
    run_id = uuid4()
    job = Job(
        tenant_id=tenant_id,
        call_id=call_id,
        kind="llm",
        status="running",
        attempt=0,
        run_after=datetime.now(UTC),
    )
    session = type("Session", (), {"execute": AsyncMock(return_value=_ScalarResult(job))})()
    staged: dict[str, object] = {}

    @asynccontextmanager
    async def fake_scope(*args: object, **kwargs: object):
        yield session

    async def fake_mark_job(*args: object, **kwargs: object) -> Job:
        job.status = str(kwargs["status"])
        job.attempt = int(kwargs["attempt"])
        return job

    async def fake_stage_job(*args: object, **kwargs: object):
        staged.update(kwargs)
        return uuid4()

    async def fake_dispatch(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(pipeline, "session_scope", fake_scope)
    monkeypatch.setattr(pipeline, "mark_job", fake_mark_job)
    monkeypatch.setattr(pipeline.outbox, "stage_job", fake_stage_job)
    monkeypatch.setattr(pipeline.outbox, "dispatch_one", fake_dispatch)

    retried = await pipeline.handle_failure(
        tenant_id=tenant_id,
        call_id=call_id,
        kind="llm",
        error_code="llm_failed",
        error_detail="invalid JSON",
        analysis_run_id=run_id,
        reanalysis=True,
        previous_status="failed_terminal",
    )

    assert retried is True
    assert job.status == "failed_retryable"
    assert job.attempt == 1
    assert staged["call_id"] == call_id
    assert staged["analysis_run_id"] == run_id
    assert staged["reanalysis"] is True
    assert staged["previous_status"] == "failed_terminal"
