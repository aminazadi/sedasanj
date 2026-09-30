from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.routers.calls import _summary
from app.services.progress import lerp, resolve, values_for_status


def test_status_defaults_cover_the_happy_path() -> None:
    assert values_for_status("stored")["progress_pct"] == 15
    assert values_for_status("transcribing")["progress_pct"] == 20
    assert values_for_status("complete")["progress_pct"] == 100


def test_failed_status_keeps_the_last_percent() -> None:
    assert "progress_pct" not in values_for_status("failed_retryable")
    assert "progress_pct" not in values_for_status("failed_terminal")
    assert "تلاش مجدد" in str(values_for_status("failed_retryable")["progress_detail"])


def test_resolve_fills_in_defaults_for_legacy_rows() -> None:
    pct, detail, processing = resolve("transcribing", None, None)
    assert pct == 20
    assert "پیاده‌سازی" in detail
    assert processing is True


def test_resolve_prefers_worker_reported_percent() -> None:
    pct, detail, processing = resolve("transcribing", 37, "پیاده‌سازی کانال مشتری — قطعه ۲ از ۴")
    assert pct == 37
    assert "قطعه" in detail
    assert processing is True


def test_complete_is_not_processing() -> None:
    pct, _, processing = resolve("complete", None, None)
    assert pct == 100
    assert processing is False


def test_lerp_maps_steps_across_a_band() -> None:
    assert lerp(22, 50, 1, 2) == 22
    assert lerp(22, 50, 1, 2, finished=True) == 36
    assert lerp(22, 50, 2, 2, finished=True) == 50
    assert lerp(60, 78, 1, 3) == 60
    assert lerp(60, 78, 3, 3, finished=True) == 78


def test_call_summary_exposes_worker_reported_progress() -> None:
    now = datetime.now(UTC)
    call = SimpleNamespace(
        id=uuid4(),
        asterisk_uniqueid="test-progress",
        caller_number="09120000000",
        dialed_number="303",
        direction="inbound",
        agent_extension="303",
        started_at=now,
        ended_at=now,
        duration_ms=10_000,
        billed_seconds=None,
        status="analyzing",
        error_code=None,
        progress_pct=76,
        progress_detail="در حال استخراج نتیجه ساختاریافته",
    )

    summary = _summary(call, None)  # type: ignore[arg-type]

    assert summary.progress_pct == 76
    assert summary.progress_detail == "در حال استخراج نتیجه ساختاریافته"
    assert summary.processing is True
