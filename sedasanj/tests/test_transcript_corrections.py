import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import get_settings
from app.services.provider_errors import ProviderError
from app.services.transcript_corrections import (
    CorrectionClient,
    advance_correction_model,
    current_correction_model,
    profile_version,
    revision_mode,
    should_run_text_correction,
    source_segments,
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


def test_source_segments_repairs_invalid_zero_length_timestamps() -> None:
    utterance = SimpleNamespace(
        id="segment-id",
        channel=0,
        t_start_ms=0,
        t_end_ms=0,
        text="سلام",
        confidence=None,
        metadata_json=None,
    )

    assert source_segments([utterance])[0]["t_end_ms"] == 1


def test_text_correction_models_advance_only_after_failure() -> None:
    revision = SimpleNamespace(
        text_models=["primary", "fallback"],
        metrics={"previous_status": "complete"},
        provider_task_id="task-primary",
        provider_submitted_at=object(),
    )

    assert current_correction_model(revision) == "primary"
    assert advance_correction_model(revision, error="technical failure") == "fallback"
    assert revision.provider_task_id is None
    assert revision.provider_submitted_at is None
    assert revision.metrics["text_model_failures"] == [
        {"model": "primary", "error": "technical failure"}
    ]

    with pytest.raises(ProviderError, match="همه مدل‌های تصحیح متن ناموفق بودند"):
        advance_correction_model(revision, error="fallback failure")


async def test_correction_submit_sends_only_current_model() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["idempotency_key"] = request.headers["Idempotency-Key"]
        return httpx.Response(202, json={"task_id": "task-primary"})

    runtime = get_settings().model_copy(
        update={
            "voicesanj_base_url": "https://aiservice.test",
            "voicesanj_api_key": "secret",
        }
    )
    revision = SimpleNamespace(
        idempotency_key="correction-stable",
        text_models=["primary", "fallback"],
        metrics={},
    )
    client = CorrectionClient(runtime)
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        task_id = await client.submit(
            revision,
            SOURCE,
            "correct carefully",
            model=current_correction_model(revision),
        )
    finally:
        await client.close()

    assert task_id == "task-primary"
    assert captured["body"]["model"] == "primary"
    assert "models" not in captured["body"]
    assert captured["idempotency_key"] == "correction-stable-text-0"


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
