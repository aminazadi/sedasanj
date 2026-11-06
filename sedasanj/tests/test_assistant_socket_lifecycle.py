import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.routers import assistant
from app.services import assistant_socket, queue


class _Rows:
    def scalars(self):
        return self

    def all(self):
        return []


@pytest.mark.asyncio
async def test_join_subscribes_before_reading_conversation_snapshot(monkeypatch) -> None:
    tenant_id = uuid4()
    owner_id = uuid4()
    conversation_id = uuid4()
    sid = "socket-session"
    events = []
    conversation = SimpleNamespace(
        id=conversation_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        mode="standard",
        title="Existing chat",
    )

    class _Session:
        async def get(self, model, key):
            assert key == conversation_id
            return conversation

        async def execute(self, statement):
            events.append("snapshot-query")
            return _Rows()

    @asynccontextmanager
    async def fake_session_scope(_tenant_id):
        yield _Session()

    async def get_session(_sid):
        return {"tenant_id": tenant_id, "owner_id": owner_id, "role": "operator"}

    async def enter_room(_sid, room):
        assert room == assistant_socket.room_for(tenant_id, owner_id, conversation_id)
        events.append("room-joined")

    async def emit(event, state, to):
        assert event == "assistant:conversation:state"
        assert state["conversation_id"] == str(conversation_id)
        assert to == sid
        events.append("state-emitted")

    monkeypatch.setattr(assistant_socket, "session_scope", fake_session_scope)
    monkeypatch.setattr(assistant_socket.sio, "get_session", get_session)
    monkeypatch.setattr(assistant_socket.sio, "enter_room", enter_room)
    monkeypatch.setattr(assistant_socket.sio, "emit", emit)

    result = await assistant_socket.join_conversation(
        sid, {"conversation_id": str(conversation_id), "after_sequence": 0}
    )

    assert result == {"ok": True, "sequence": 0}
    assert events == ["room-joined", *(["snapshot-query"] * 3), "state-emitted"]


@pytest.mark.asyncio
async def test_terminal_run_does_not_publish_late_stream_events(monkeypatch) -> None:
    tenant_id, run_id = uuid4(), uuid4()
    run = SimpleNamespace(id=run_id, status="failed")

    class _Session:
        async def scalar(self, statement):
            assert "FOR UPDATE" in str(statement)
            return run

    @asynccontextmanager
    async def fake_session_scope(_tenant_id):
        yield _Session()

    monkeypatch.setattr(assistant_socket, "session_scope", fake_session_scope)
    assert await assistant_socket.publish(tenant_id, run_id, "delta", {"content": "late"}) == {}


@pytest.mark.asyncio
async def test_running_assistant_job_cannot_start_twice(monkeypatch) -> None:
    from worker_llm.main import run_assistant_chat

    tenant_id, run_id = uuid4(), uuid4()

    class _Session:
        async def scalar(self, statement):
            assert "FOR UPDATE" in str(statement)
            return SimpleNamespace(status="running")

    @asynccontextmanager
    async def fake_session_scope(_tenant_id):
        yield _Session()

    monkeypatch.setattr("worker_llm.main.session_scope", fake_session_scope)
    assert (
        await run_assistant_chat({}, {"tenant_id": str(tenant_id), "run_id": str(run_id)})
        == "already finished"
    )


@pytest.mark.parametrize(("dedicated", "canary"), [(False, False), (False, True), (True, False)])
async def test_assistant_job_contains_only_durable_ids(monkeypatch, dedicated, canary) -> None:
    tenant_id, run_id = uuid4(), uuid4()
    enqueued = []

    async def enqueue(*args, **kwargs):
        enqueued.append((args, kwargs))

    monkeypatch.setattr(
        queue,
        "get_settings",
        lambda: SimpleNamespace(
            assistant_dedicated_queue=dedicated,
            assistant_dedicated_tenants=(tenant_id,) if canary else (),
        ),
    )
    monkeypatch.setattr(queue, "get_queue", lambda: SimpleNamespace(enqueue=enqueue))
    await queue.enqueue_assistant(tenant_id, run_id)

    assert enqueued == [
        (
            (
                queue.QUEUE_ASSISTANT if dedicated or canary else queue.QUEUE_LLM,
                "run_assistant_chat",
                {"run_id": str(run_id), "tenant_id": str(tenant_id)},
            ),
            {"job_id": f"assistant:{run_id}"},
        )
    ]


def test_assistant_worker_uses_json_and_only_consumes_its_own_queue() -> None:
    from arq.worker import get_kwargs

    from worker_llm.main import AssistantWorkerSettings, run_assistant_chat

    settings = get_kwargs(AssistantWorkerSettings)
    assert settings["queue_name"] == queue.QUEUE_ASSISTANT
    assert settings["functions"] == [run_assistant_chat]
    assert settings["job_serializer"] is queue.job_serializer
    assert settings["job_deserializer"] is queue.job_deserializer


async def test_dispatch_cleanup_visits_every_tenant_after_one_fails(monkeypatch) -> None:
    tenant_ids = [uuid4(), uuid4(), uuid4()]
    visited = []

    @asynccontextmanager
    async def session_scope(_tenant_id, *, staff):
        class _Session:
            async def execute(self, _statement):
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: tenant_ids))

        assert staff
        yield _Session()

    async def dispatch(tenant_id, cutoff):
        visited.append((tenant_id, cutoff))
        if tenant_id == tenant_ids[0]:
            raise RuntimeError("tenant offline")

    async def stop(_seconds):
        raise asyncio.CancelledError()

    monkeypatch.setattr(assistant_socket, "session_scope", session_scope)
    monkeypatch.setattr(assistant_socket, "_dispatch_tenant_pending", dispatch)
    monkeypatch.setattr(assistant_socket.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await assistant_socket._dispatch_pending()

    assert [tenant_id for tenant_id, _cutoff in visited] == tenant_ids
    assert visited[0][1] is not None
    assert all(cutoff == visited[0][1] for _tenant_id, cutoff in visited)


async def test_deltas_flush_while_provider_is_waiting_and_close_cleanly() -> None:
    release_provider = asyncio.Event()
    closed = asyncio.Event()

    async def chunks():
        yield "پاسخ"
        yield " فارسی"
        yield " دقیق"
        try:
            await release_provider.wait()
        finally:
            closed.set()

    batches = assistant._coalesced_deltas(chunks())
    assert await anext(batches) == "پاسخ"
    assert await asyncio.wait_for(anext(batches), timeout=2) == " فارسی دقیق"
    await batches.aclose()
    assert closed.is_set()


async def test_deltas_flush_on_end_without_losing_text() -> None:
    async def chunks():
        for value in ("اول", "دوم", "سوم"):
            yield value

    assert [batch async for batch in assistant._coalesced_deltas(chunks())] == ["اول", "دومسوم"]


async def test_stopping_after_first_delta_closes_the_provider_stream() -> None:
    closed = asyncio.Event()

    async def chunks():
        try:
            yield "پاسخ"
            yield "ادامه"
        finally:
            closed.set()

    batches = assistant._coalesced_deltas(chunks())
    assert await anext(batches) == "پاسخ"
    await batches.aclose()
    assert closed.is_set()
