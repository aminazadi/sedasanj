from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import assistant_socket


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
    assert events == ["room-joined", "snapshot-query", "snapshot-query", "snapshot-query", "state-emitted"]


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
    assert await run_assistant_chat(
        {}, {"tenant_id": str(tenant_id), "run_id": str(run_id)}
    ) == "already finished"
