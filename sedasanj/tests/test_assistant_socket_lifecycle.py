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
    assert events == ["room-joined", "snapshot-query", "snapshot-query", "state-emitted"]
