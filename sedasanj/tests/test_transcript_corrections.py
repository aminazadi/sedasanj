import pytest

from app.config import get_settings
from app.services.transcript_corrections import (
    profile_version,
    revision_mode,
    should_run_text_correction,
    validate_result,
)

SOURCE = [
    {
        "id": "one",
        "channel": 0,
        "t_start_ms": 100,
        "t_end_ms": 900,
        "text": "شماره سفارش ۱۲۳ است",
    },
    {
        "id": "two",
        "channel": 1,
        "t_start_ms": 950,
        "t_end_ms": 1600,
        "text": "بله ثبت شد",
    },
]


def test_profile_version_changes_with_prompt() -> None:
    runtime = get_settings()
    changed = runtime.model_copy(update={"correction_prompt": runtime.correction_prompt + " دقیق"})
    assert profile_version(runtime) != profile_version(changed)


def test_manual_correction_always_uses_text_processing() -> None:
    runtime = get_settings().model_copy(update={"correction_mode": "audio_only"})

    assert revision_mode(runtime, "manual") == "text_only"
    assert revision_mode(runtime, "automatic") == "audio_only"
    assert should_run_text_correction("audio_only", "manual") is True
    assert should_run_text_correction("audio_only", "automatic") is False


def test_validated_segments_preserve_identity_and_mark_uncertain() -> None:
    result = {
        "finish_reason": "stop",
        "segments": [
            {"id": "one", "corrected_text": "شماره سفارش ۱۲۳ است.", "uncertain": False},
            {"id": "two", "corrected_text": "بله، ثبت شد.", "uncertain": True},
        ],
        "uncertain_items": [
            {"segment_id": "two", "source": "ثبت شد", "suggestion": "ثبت شد", "reason": "noise"}
        ],
    }
    segments, uncertain = validate_result(SOURCE, result, max_uncertain_ratio=0.5)
    assert [row["id"] for row in segments] == ["one", "two"]
    assert segments[1]["uncertain"] is True
    assert uncertain[0]["segment_id"] == "two"


@pytest.mark.parametrize(
    "result",
    [
        {"finish_reason": "length", "segments": [], "uncertain_items": []},
        {
            "finish_reason": "stop",
            "segments": [{"id": "two", "corrected_text": "x", "uncertain": False}],
            "uncertain_items": [],
        },
        {
            "finish_reason": "stop",
            "segments": [
                {"id": "one", "corrected_text": "شماره سفارش ۹۹۹ است", "uncertain": False},
                {"id": "two", "corrected_text": "بله ثبت شد", "uncertain": False},
            ],
            "uncertain_items": [],
        },
    ],
)
def test_validation_rejects_incomplete_reordered_or_critical_changes(result: dict) -> None:
    with pytest.raises(ValueError):
        validate_result(SOURCE, result, max_uncertain_ratio=0.5)
