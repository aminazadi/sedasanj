"""Import uploads must not pin a DB connection while the client streams (WSTG-BUSL / DoS)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.routers import organization_data as module
from app.services.organization_data import archive


class _Tracker:
    def __init__(self) -> None:
        self.open_sessions = 0
        self.seen_during_stream: list[int] = []

    @asynccontextmanager
    async def __call__(self):  # type: ignore[no-untyped-def]
        self.open_sessions += 1
        try:
            yield SimpleNamespace()
        finally:
            self.open_sessions -= 1


def _request(stream: Any) -> Any:
    return SimpleNamespace(
        headers={"content-type": "application/octet-stream"},
        stream=stream,
    )


@pytest.fixture()
def tracker(monkeypatch: pytest.MonkeyPatch) -> _Tracker:
    tracker = _Tracker()
    row = SimpleNamespace(id=uuid4(), size_bytes=None, state="uploading", due_at=None)

    async def fake_run(*_args: Any, **_kwargs: Any) -> Any:
        return row

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    class _Storage:
        async def ensure_bucket(self) -> None:
            return None

        async def put_path(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(module, "control_session_scope", tracker)
    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module, "_assert_import", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "_audit", noop)
    monkeypatch.setattr(module, "_view", lambda r, _p: {"state": r.state})
    monkeypatch.setattr(module, "get_storage", lambda: _Storage())
    monkeypatch.setattr(module.jobs, "file_key", lambda _row: "k")
    return tracker


@pytest.mark.asyncio
async def test_no_db_session_is_open_while_the_body_streams(tracker: _Tracker) -> None:
    async def stream() -> Any:
        tracker.seen_during_stream.append(tracker.open_sessions)
        yield archive.MAGIC + b"payload"
        tracker.seen_during_stream.append(tracker.open_sessions)

    result = await module.upload_import(uuid4(), _request(stream), SimpleNamespace())  # type: ignore[arg-type]
    assert result == {"state": "queued"}
    assert tracker.seen_during_stream == [0, 0]


@pytest.mark.asyncio
async def test_stalled_upload_is_cut_off(
    tracker: _Tracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "UPLOAD_STALL_SECONDS", 0.05)

    async def stream() -> Any:
        yield archive.MAGIC
        await asyncio.sleep(5)
        yield b"never"

    with pytest.raises(ApiError):
        await module.upload_import(uuid4(), _request(stream), SimpleNamespace())  # type: ignore[arg-type]
    assert tracker.open_sessions == 0
