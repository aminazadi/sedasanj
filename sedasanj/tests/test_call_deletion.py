from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.routers import calls
from app.services.storage import MemoryStorage


@pytest.mark.asyncio
async def test_delete_call_removes_audio_and_call_owned_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_id, tenant_id, audio_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    call = SimpleNamespace(id=call_id, audio_id=audio_id)
    audio = SimpleNamespace(id=audio_id, tenant_id=tenant_id, object_key="tenant/call.wav")
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: audio),
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
            ]
        ),
        delete=AsyncMock(),
        flush=AsyncMock(),
    )
    storage = MemoryStorage()
    await storage.put(audio.object_key, b"RIFFsample")
    audit_record = AsyncMock()
    monkeypatch.setattr(calls, "_load_call", AsyncMock(return_value=call))
    monkeypatch.setattr(calls, "get_storage", lambda: storage)
    monkeypatch.setattr(calls.audit, "record", audit_record)

    await calls.delete_call(
        call_id,
        SimpleNamespace(headers={}, client=None),
        SimpleNamespace(id=user_id, tenant_id=tenant_id),
        session,
    )

    session.delete.assert_awaited_once_with(call)
    assert audio.object_key not in storage.objects
    assert session.execute.await_count == 5
    audit_record.assert_awaited_once()
