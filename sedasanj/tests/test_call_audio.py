from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.routers import calls
from app.services.storage import MemoryStorage


@pytest.mark.asyncio
async def test_call_audio_content_serves_available_file(monkeypatch: pytest.MonkeyPatch) -> None:
    call_id, tenant_id, audio_id = uuid4(), uuid4(), uuid4()
    audio = SimpleNamespace(
        id=audio_id, tenant_id=tenant_id, object_key="tenant/call.wav", deleted_at=None
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: audio))
    )
    storage = MemoryStorage()
    await storage.put(audio.object_key, b"RIFFsample")
    monkeypatch.setattr(
        calls, "_load_call", AsyncMock(return_value=SimpleNamespace(audio_id=audio_id))
    )
    monkeypatch.setattr(calls, "get_storage", lambda: storage)

    result = await calls.get_call_audio_content(
        call_id, SimpleNamespace(tenant_id=tenant_id), session
    )

    assert result.body == b"RIFFsample"
    assert result.media_type == "audio/wav"


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted", [False, True])
async def test_call_audio_content_rejects_missing_or_deleted_file(
    monkeypatch: pytest.MonkeyPatch, deleted: bool
) -> None:
    call_id, tenant_id, audio_id = uuid4(), uuid4(), uuid4()
    audio = SimpleNamespace(
        object_key="tenant/missing.wav", deleted_at=object() if deleted else None
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: audio))
    )
    monkeypatch.setattr(
        calls, "_load_call", AsyncMock(return_value=SimpleNamespace(audio_id=audio_id))
    )
    monkeypatch.setattr(calls, "get_storage", MemoryStorage)

    with pytest.raises(ApiError, match="audio") as exc_info:
        await calls.get_call_audio_content(call_id, SimpleNamespace(tenant_id=tenant_id), session)
    assert exc_info.value.code == "not_found"
