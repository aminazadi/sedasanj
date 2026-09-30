from __future__ import annotations

import pytest

from app.services.storage import MemoryStorage


def test_object_key_layout_has_no_phone_number() -> None:
    from uuid import uuid4

    tenant_id, call_id = uuid4(), uuid4()
    key = f"{tenant_id}/{call_id}.wav"
    assert key.startswith(f"{tenant_id}/")
    assert key.endswith(".wav")
    assert "0912" not in key


async def test_memory_storage_roundtrip_and_delete() -> None:
    storage = MemoryStorage()
    await storage.ensure_bucket()
    await storage.put("tenant/call.wav", b"RIFF....")
    assert await storage.get("tenant/call.wav") == b"RIFF...."
    assert "tenant/call.wav" in await storage.presigned_url("tenant/call.wav", 60)
    await storage.delete("tenant/call.wav")
    with pytest.raises(KeyError):
        await storage.get("tenant/call.wav")
