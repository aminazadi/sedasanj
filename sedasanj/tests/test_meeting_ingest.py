"""Chunk intake rules that do not need a database."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from meeting_helpers import RecordingQueue, sha256, wav_bytes

from app.errors import ApiError
from app.services import meeting_ingest
from app.services.meeting_ingest import ChunkUpload, accept_chunk
from app.services.queue import QUEUE_MEETING, set_queue


def _upload(path: Path, audio: bytes, **overrides: object) -> ChunkUpload:
    path.write_bytes(audio)
    values: dict[str, object] = {
        "path": path,
        "declared_sha256": sha256(audio),
        "t_start_ms": 0,
        "t_end_ms": 1000,
    }
    values.update(overrides)
    return ChunkUpload(**values)  # type: ignore[arg-type]


def _meeting(status: str = "receiving") -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), status=status)


def test_storage_key_and_job_id_are_stable() -> None:
    tenant, meeting, chunk = uuid4(), uuid4(), uuid4()
    assert (
        meeting_ingest.chunk_object_key(tenant, meeting, 7) == f"{tenant}/meetings/{meeting}/7.wav"
    )
    assert meeting_ingest.chunk_job_id(chunk) == f"meeting-chunk:{chunk}"
    assert meeting_ingest.chunk_job_id(chunk) == meeting_ingest.chunk_job_id(chunk)


def test_device_text_keeps_only_documented_fields_and_bounds_them() -> None:
    cleaned = meeting_ingest.clean_device_text(
        [{"t_start_ms": "10", "t_end_ms": 20, "text": "x" * 5000, "extra": "dropped"}]
    )
    assert cleaned == [{"t_start_ms": 10, "t_end_ms": 20, "text": "x" * 2000}]
    assert meeting_ingest.clean_device_text(None) is None
    assert meeting_ingest.clean_device_text([]) is None
    many = [{"t_start_ms": i, "t_end_ms": i, "text": "a"} for i in range(500)]
    assert len(meeting_ingest.clean_device_text(many) or []) == meeting_ingest.MAX_DEVICE_TEXT_ITEMS
    with pytest.raises(ApiError) as bad:
        meeting_ingest.clean_device_text([{"text": "no times"}])
    assert bad.value.code == "invalid_request"


async def test_enqueue_uses_the_meeting_queue_and_a_stable_job_id() -> None:
    queue = RecordingQueue()
    set_queue(queue)
    try:
        tenant, meeting, chunk = uuid4(), uuid4(), uuid4()
        assert await meeting_ingest.enqueue_chunk(tenant, meeting, chunk) is True
        assert await meeting_ingest.enqueue_chunk(tenant, meeting, chunk) is True
    finally:
        set_queue(None)
    assert [job[0] for job in queue.jobs] == [QUEUE_MEETING, QUEUE_MEETING]
    assert queue.jobs[0][2] == {
        "tenant_id": str(tenant),
        "meeting_id": str(meeting),
        "chunk_id": str(chunk),
    }
    assert queue.job_ids == [f"meeting-chunk:{chunk}"] * 2


async def test_enqueue_failure_is_not_an_error() -> None:
    queue = RecordingQueue()
    queue.fail = True
    set_queue(queue)
    try:
        assert await meeting_ingest.enqueue_chunk(uuid4(), uuid4(), uuid4()) is False
    finally:
        set_queue(None)


async def test_closed_meetings_refuse_chunks(tmp_path: Path) -> None:
    for status in ("processing", "complete", "canceled", "failed_terminal"):
        with pytest.raises(ApiError) as refused:
            await accept_chunk(
                None,
                _meeting(status),
                0,
                _upload(tmp_path / "c.wav", wav_bytes(1)),  # type: ignore[arg-type]
            )
        assert refused.value.code == "meeting_closed"


async def test_time_range_and_hash_are_checked_before_any_storage(tmp_path: Path) -> None:
    audio = wav_bytes(1)
    with pytest.raises(ApiError) as backwards:
        await accept_chunk(
            None,
            _meeting(),
            0,
            _upload(tmp_path / "a.wav", audio, t_start_ms=5, t_end_ms=1),  # type: ignore[arg-type]
        )
    assert backwards.value.code == "invalid_request"

    with pytest.raises(ApiError) as mismatch:
        await accept_chunk(
            None,
            _meeting(),
            0,
            _upload(tmp_path / "b.wav", audio, declared_sha256="a" * 64),  # type: ignore[arg-type]
        )
    assert mismatch.value.code == "meeting_chunk_invalid_audio"
