from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.routers import assistant


class _Session:
    def __init__(self, message, earlier_user_messages: int = 1) -> None:
        self.message = message
        self.earlier_user_messages = earlier_user_messages
        self.deleted = None

    async def get(self, model, message_id):
        return self.message if self.message.id == message_id else None

    async def scalar(self, statement):
        return self.earlier_user_messages

    async def execute(self, statement):
        self.deleted = statement


@pytest.mark.asyncio
async def test_delete_message_tail_is_owner_scoped_and_resets_first_title(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    owner_id = uuid4()
    conversation_id = uuid4()
    message_id = uuid4()
    conversation = SimpleNamespace(
        id=conversation_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        title="old title",
        updated_at=None,
    )
    message = SimpleNamespace(
        id=message_id,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        role="user",
        created_at=object(),
    )
    session = _Session(message, earlier_user_messages=0)
    recorded = {}

    async def fake_conversation(*args):
        assert args[1:] == (conversation_id, tenant_id, owner_id)
        return conversation

    async def fake_record(*args, **kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(assistant, "_conversation", fake_conversation)
    monkeypatch.setattr(assistant.audit, "record", fake_record)

    await assistant.delete_message_tail(
        conversation_id,
        message_id,
        SimpleNamespace(headers={}, client=None),
        SimpleNamespace(id=owner_id, tenant_id=tenant_id),
        session,
    )

    assert conversation.title is None
    assert conversation.updated_at is not None
    assert session.deleted is not None
    assert "DELETE FROM chat_messages" in str(session.deleted)
    assert recorded["action"] == "assistant.message_tail_delete"


@pytest.mark.asyncio
async def test_delete_message_tail_rejects_assistant_message(monkeypatch) -> None:
    tenant_id = uuid4()
    owner_id = uuid4()
    conversation_id = uuid4()
    message = SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        role="assistant",
        created_at=object(),
    )
    session = _Session(message)

    async def fake_conversation(*args):
        return SimpleNamespace(id=conversation_id)

    monkeypatch.setattr(assistant, "_conversation", fake_conversation)

    with pytest.raises(ApiError, match="user message not found"):
        await assistant.delete_message_tail(
            conversation_id,
            message.id,
            SimpleNamespace(headers={}, client=None),
            SimpleNamespace(id=owner_id, tenant_id=tenant_id),
            session,
        )

    assert session.deleted is None
