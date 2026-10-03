from __future__ import annotations

from pathlib import Path

from worker_asr.engine import FixtureEngine, _segments_from_whisper
from worker_asr.main import build_full_text, consolidate_segments


async def test_fixture_engine_is_deterministic(wav_file) -> None:
    path: Path = wav_file(seconds=2.0)
    engine = FixtureEngine()
    first = await engine.transcribe(path)
    second = await engine.transcribe(path)
    assert first == second
    assert first[0].text
    assert first[0].t_end_ms > first[0].t_start_ms


async def test_fixture_engine_reports_a_model_identity() -> None:
    engine = FixtureEngine()
    assert engine.model_name
    assert engine.model_version


def test_whisper_segments_replace_zero_end_time_with_audio_duration(wav_file) -> None:
    path: Path = wav_file(seconds=2.0)

    segments = _segments_from_whisper(
        {"text": "سلام", "segments": [{"start": 0, "end": 0, "text": "سلام"}]},
        path,
    )

    assert len(segments) == 1
    assert segments[0].t_start_ms == 0
    assert segments[0].t_end_ms == 2_000


def test_full_text_labels_channels_and_sorts_by_time() -> None:
    from worker_asr.engine import AsrSegment

    rows = [
        (1, AsrSegment(t_start_ms=4_000, t_end_ms=6_000, text="بله بفرمایید")),
        (0, AsrSegment(t_start_ms=0, t_end_ms=3_000, text="سلام")),
    ]
    text = build_full_text(rows)
    lines = text.splitlines()
    assert lines[0].startswith("[caller 00:00]")
    assert "سلام" in lines[0]
    assert "agent" in lines[1]
    assert "00:04" in lines[1]


def test_consolidate_segments_merges_word_sized_parts_into_turns() -> None:
    from worker_asr.engine import AsrSegment

    rows = [
        (0, AsrSegment(t_start_ms=0, t_end_ms=300, text=" سلام ")),
        (0, AsrSegment(t_start_ms=350, t_end_ms=700, text="وقت بخیر")),
        (1, AsrSegment(t_start_ms=900, t_end_ms=1_300, text="بفرمایید")),
        (1, AsrSegment(t_start_ms=1_400, t_end_ms=1_800, text="در خدمتم")),
    ]

    merged = consolidate_segments(rows)

    assert [(channel, segment.text) for channel, segment in merged] == [
        (0, "سلام وقت بخیر"),
        (1, "بفرمایید در خدمتم"),
    ]
    assert merged[0][1].t_start_ms == 0
    assert merged[0][1].t_end_ms == 700


def test_consolidate_segments_preserves_overlapping_other_speaker() -> None:
    from worker_asr.engine import AsrSegment

    rows = [
        (0, AsrSegment(t_start_ms=0, t_end_ms=1_000, text="صدای من میاد؟")),
        (1, AsrSegment(t_start_ms=500, t_end_ms=900, text="بله")),
        (0, AsrSegment(t_start_ms=1_050, t_end_ms=1_500, text="ممنون")),
    ]

    merged = consolidate_segments(rows)

    assert [channel for channel, _ in merged] == [0, 1, 0]
    assert [segment.text for _, segment in merged] == ["صدای من میاد؟", "بله", "ممنون"]


def test_consolidate_segments_suppresses_exact_repeated_part() -> None:
    from worker_asr.engine import AsrSegment

    rows = [
        (0, AsrSegment(t_start_ms=0, t_end_ms=500, text="سلام")),
        (0, AsrSegment(t_start_ms=450, t_end_ms=900, text="سلام")),
    ]

    merged = consolidate_segments(rows)

    assert len(merged) == 1
    assert merged[0][1].text == "سلام"
    assert merged[0][1].t_end_ms == 900


def test_consolidate_segments_keeps_spoken_repetition_after_a_pause() -> None:
    from worker_asr.engine import AsrSegment

    rows = [
        (0, AsrSegment(t_start_ms=0, t_end_ms=300, text="بله")),
        (0, AsrSegment(t_start_ms=500, t_end_ms=800, text="بله")),
    ]

    merged = consolidate_segments(rows)

    assert len(merged) == 1
    assert merged[0][1].text == "بله بله"
