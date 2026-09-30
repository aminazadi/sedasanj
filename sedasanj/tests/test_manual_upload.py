from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.errors import ApiError
from app.services.ingest import resolve_uniqueid, resolve_window


def test_resolve_uniqueid_keeps_an_explicit_value() -> None:
    assert resolve_uniqueid("  local-1  ") == "local-1"


def test_resolve_uniqueid_mints_a_manual_id_when_blank() -> None:
    value = resolve_uniqueid("  ")
    assert value.startswith("manual-")
    assert len(value) > 8


def test_resolve_window_defaults_to_now_minus_duration() -> None:
    before = datetime.now(UTC)
    started, ended = resolve_window(None, None, 135_000)
    after = datetime.now(UTC)
    assert ended - started == timedelta(milliseconds=135_000)
    assert before - timedelta(seconds=1) <= ended <= after + timedelta(seconds=1)


def test_resolve_window_fills_the_missing_end() -> None:
    started = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    start, end = resolve_window(started, None, 2_000)
    assert start == started
    assert end == started + timedelta(milliseconds=2_000)


def test_resolve_window_rejects_an_inverted_range() -> None:
    started = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    ended = started - timedelta(seconds=1)
    with pytest.raises(ApiError, match="ended_at"):
        resolve_window(started, ended, 1_000)
