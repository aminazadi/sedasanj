from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.deps import Principal
from app.errors import ApiError
from app.models import AsrTranscriptRevision, AudioObject, Call, Job, Tenant, Transcript
from app.routers import calls


class _Result:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one(self) -> object:
        assert self.value is not None
        return self.value

    def scalar_one_or_none(self) -> object | None:
        return self.value


class _Session:
    def __init__(self, values: list[object | None], tenant: Tenant) -> None:
        self.values = iter(values)
        self.tenant = tenant
        self.added: list[object] = []

    async def execute(self, statement: object) -> _Result:
        return _Result(next(self.values))

    async def get(self, model: object, key: object) -> object | None:
        return self.tenant if model is Tenant and key == self.tenant.id else None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, Job) and value.id is None:
                value.id = uuid4()


def _rows(status: str = "failed_terminal") -> tuple[Call, AudioObject, Job, Tenant]:
    tenant_id = uuid4()
    call_id = uuid4()
    audio_id = uuid4()
    call = Call(
        id=call_id,
        tenant_id=tenant_id,
        audio_id=audio_id,
        status=status,
        error_code="asr_failed",
    )
    audio = AudioObject(
        id=audio_id,
        tenant_id=tenant_id,
        duration_ms=57_000,
        deleted_at=None,
    )
    job = Job(
        id=uuid4(),
        tenant_id=tenant_id,
        call_id=call_id,
        kind="asr",
        status="failed_terminal",
        attempt=5,
        run_after=datetime.now(UTC),
    )
    tenant = Tenant(id=tenant_id, price_per_minute_toman=10_000)
    return call, audio, job, tenant


@pytest.mark.asyncio
async def test_retry_transcription_creates_a_fresh_job_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call, audio, previous_job, tenant = _rows()
    session = _Session([call, None, audio, previous_job], tenant)
    events: list[str] = []

    async def load_call(*args: object, **kwargs: object) -> Call:
        principal = args[3]
        assert isinstance(principal, Principal)
        assert principal.role == "operator"
        return call

    @asynccontextmanager
    async def scope(*args: object, **kwargs: object):
        events.append("begin")
        yield session
        events.append("commit")

    async def reserve(*args: object, **kwargs: object) -> None:
        events.append("reserve")

    async def record(*args: object, **kwargs: object) -> None:
        events.append("processing_event")

    async def audit_record(*args: object, **kwargs: object) -> None:
        events.append("audit")

    async def stage(*args: object, **kwargs: object):
        events.append("stage")
        return uuid4()

    async def dispatch(*args: object, **kwargs: object) -> bool:
        assert "commit" in events
        events.append("dispatch")
        return True

    monkeypatch.setattr(calls, "_load_call", load_call)
    monkeypatch.setattr(calls, "session_scope", scope)
    monkeypatch.setattr(calls.billing, "reserve_retry", reserve)
    monkeypatch.setattr(calls.processing_events, "record", record)
    monkeypatch.setattr(calls.audit, "record", audit_record)
    monkeypatch.setattr(calls.outbox, "stage_job", stage)
    monkeypatch.setattr(calls.outbox, "dispatch_one", dispatch)
    monkeypatch.setattr(calls, "client_ip", lambda request: "127.0.0.1")

    async def models(session: object) -> dict[str, str]:
        return {"asr_ai_provider": "aiservice", "asr_model": "asr-model"}

    monkeypatch.setattr(calls, "effective_models", models)

    principal = Principal(
        kind="user",
        id=uuid4(),
        tenant_id=tenant.id,
        role="operator",
    )
    result = await calls.retry_transcription(call.id, None, principal)  # type: ignore[arg-type]

    new_jobs = [value for value in session.added if isinstance(value, Job)]
    assert len(new_jobs) == 1
    assert new_jobs[0].id != previous_job.id
    assert new_jobs[0].status == "queued"
    assert call.status == "stored"
    assert call.error_code is None
    assert result == {"status": "queued", "job_id": str(new_jobs[0].id)}
    assert events == [
        "begin",
        "reserve",
        "processing_event",
        "audit",
        "stage",
        "commit",
        "dispatch",
    ]


@pytest.mark.asyncio
async def test_retry_transcription_rejects_a_duplicate_active_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call, _audio, _job, tenant = _rows(status="stored")
    session = _Session([call, None], tenant)

    async def load_call(*args: object, **kwargs: object) -> Call:
        return call

    @asynccontextmanager
    async def scope(*args: object, **kwargs: object):
        yield session

    monkeypatch.setattr(calls, "_load_call", load_call)
    monkeypatch.setattr(calls, "session_scope", scope)
    principal = Principal(kind="user", id=uuid4(), tenant_id=tenant.id, role="org_admin")

    with pytest.raises(ApiError, match="قابل پردازش مجدد نیست"):
        await calls.retry_transcription(call.id, None, principal)  # type: ignore[arg-type]

    assert session.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transcript", "audio", "job_status", "message"),
    [
        (uuid4(), "present", "failed_terminal", "قبلاً ایجاد شده"),
        (None, None, "failed_terminal", "در دسترس نیست"),
        (None, "present", "failed_retryable", "خطای نهایی تبدیل گفتار"),
    ],
)
async def test_retry_transcription_rejects_ineligible_calls(
    monkeypatch: pytest.MonkeyPatch,
    transcript: object | None,
    audio: str | None,
    job_status: str,
    message: str,
) -> None:
    call, audio_row, job, tenant = _rows()
    job.status = job_status
    values: list[object | None] = [call, transcript]
    if transcript is None:
        values.append(audio_row if audio == "present" else None)
    if transcript is None and audio == "present":
        values.append(job)
    session = _Session(values, tenant)

    async def load_call(*args: object, **kwargs: object) -> Call:
        return call

    @asynccontextmanager
    async def scope(*args: object, **kwargs: object):
        yield session

    monkeypatch.setattr(calls, "_load_call", load_call)
    monkeypatch.setattr(calls, "session_scope", scope)
    principal = Principal(kind="user", id=uuid4(), tenant_id=tenant.id, role="operator")

    with pytest.raises(ApiError, match=message):
        await calls.retry_transcription(call.id, None, principal)  # type: ignore[arg-type]

    assert session.added == []


@pytest.mark.asyncio
async def test_retry_transcription_does_not_mutate_state_when_credit_is_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call, audio, previous_job, tenant = _rows()
    session = _Session([call, None, audio, previous_job], tenant)

    async def load_call(*args: object, **kwargs: object) -> Call:
        return call

    @asynccontextmanager
    async def scope(*args: object, **kwargs: object):
        yield session

    async def reserve(*args: object, **kwargs: object) -> None:
        raise ApiError("insufficient_credit", "insufficient")

    monkeypatch.setattr(calls, "_load_call", load_call)
    monkeypatch.setattr(calls, "session_scope", scope)
    monkeypatch.setattr(calls.billing, "reserve_retry", reserve)
    principal = Principal(kind="user", id=uuid4(), tenant_id=tenant.id, role="operator")

    with pytest.raises(ApiError, match="insufficient"):
        await calls.retry_transcription(call.id, None, principal)  # type: ignore[arg-type]

    assert call.status == "failed_terminal"
    assert call.error_code == "asr_failed"
    assert session.added == []


@pytest.mark.asyncio
async def test_retranscription_creates_revision_without_reserving_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call, audio, _previous_job, tenant = _rows(status="complete")
    transcript = Transcript(
        call_id=call.id,
        tenant_id=tenant.id,
        full_text="متن فعلی",
        asr_model="current-model",
        asr_version="1",
    )

    class Session(_Session):
        async def get(self, model: object, key: object) -> object | None:
            if model is Transcript and key == call.id:
                return transcript
            return await super().get(model, key)

        async def flush(self) -> None:
            await super().flush()
            for value in self.added:
                if isinstance(value, AsrTranscriptRevision) and value.id is None:
                    value.id = uuid4()

    session = Session([call, audio, None], tenant)
    staged: dict[str, object] = {}

    async def load_call(*args: object, **kwargs: object) -> Call:
        return call

    @asynccontextmanager
    async def scope(*args: object, **kwargs: object):
        yield session

    async def reject_credit(*args: object, **kwargs: object) -> None:
        raise AssertionError("retranscription must not reserve credit")

    async def no_op(*args: object, **kwargs: object) -> None:
        return None

    async def stage(*args: object, **kwargs: object):
        staged.update(kwargs)
        return uuid4()

    async def dispatch(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(calls, "_load_call", load_call)
    monkeypatch.setattr(calls, "session_scope", scope)
    monkeypatch.setattr(calls.billing, "reserve_retry", reject_credit)
    monkeypatch.setattr(calls.processing_events, "record", no_op)
    monkeypatch.setattr(calls.audit, "record", no_op)
    monkeypatch.setattr(calls.outbox, "stage_job", stage)
    monkeypatch.setattr(calls.outbox, "dispatch_one", dispatch)
    monkeypatch.setattr(calls, "client_ip", lambda request: "127.0.0.1")
    async def models(session: object) -> dict[str, str]:
        return {"asr_ai_provider": "aiservice", "asr_model": "asr-model"}

    monkeypatch.setattr(calls, "effective_models", models)
    principal = Principal(kind="user", id=uuid4(), tenant_id=tenant.id, role="operator")

    result = await calls.retranscribe_call(call.id, None, principal)  # type: ignore[arg-type]

    revisions = [value for value in session.added if isinstance(value, AsrTranscriptRevision)]
    assert len(revisions) == 1
    assert revisions[0].status == "queued"
    assert revisions[0].trigger == "manual"
    assert result == {"status": "queued", "asr_revision_id": str(revisions[0].id)}
    assert staged["retranscription"] is True
    assert staged["recovery"] is True
    assert staged["previous_status"] == "complete"
