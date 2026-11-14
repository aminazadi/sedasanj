from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import call as awaited
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
    audio = SimpleNamespace(
        id=audio_id,
        tenant_id=tenant_id,
        bucket="audio",
        object_key=f"{tenant_id}/call.wav",
        bytes=len(b"RIFFsample"),
        deleted_at=None,
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: audio),
                # billing.release_held_calls: no held reservation for this call
                SimpleNamespace(
                    distinct=lambda: None,
                    scalars=lambda: SimpleNamespace(all=lambda: []),
                ),
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
            ]
        ),
        scalar=AsyncMock(return_value=False),
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

    session.delete.assert_has_awaits([awaited(call), awaited(audio)])
    assert audio.object_key in storage.objects
    assert audio.deleted_at is not None
    assert session.execute.await_count == 6
    assert session.execute.call_args.args[0].table.name == "audio_deletions"
    audit_record.assert_awaited_once()
