from __future__ import annotations

import httpx
import pytest

from app.services.provider_errors import (
    ProviderError,
    classify_failure,
    classify_http,
    inspect_payload,
)


def test_http_402_is_a_credit_error() -> None:
    error = classify_http(402, '{"error":"insufficient credits"}', kind="asr")
    assert error is not None
    assert error.code == "asr_provider_credit"
    assert error.retryable is False
    assert "VoiceSanj" in error.detail


def test_http_200_with_credit_message_is_a_credit_error() -> None:
    error = classify_http(200, '{"error":{"message":"quota exceeded"}}', kind="llm")
    assert error is not None
    assert error.code == "llm_provider_credit"


def test_http_200_completion_may_contain_credit_words() -> None:
    error = classify_http(
        200,
        '{"choices":[{"message":{"content":"اعتبار قرارداد تأیید شد"}}]}',
        kind="llm",
    )

    assert error is None


def test_empty_whisper_text_gets_a_readable_message() -> None:
    code, detail, retryable = classify_failure(
        RuntimeError("whisper returned empty text"), kind="asr"
    )
    assert code == "asr_empty_transcript"
    assert retryable is None
    assert "متن" in detail
    assert "GapGPT" not in detail


def test_timeout_classification_is_retryable_and_specific() -> None:
    code, detail, retryable = classify_failure(TimeoutError(), kind="llm")

    assert code == "llm_timeout"
    assert "زمان پردازش" in detail
    assert retryable is True


def test_dns_failure_is_retryable_and_specific() -> None:
    error = httpx.ConnectError(
        "[Errno 8] nodename nor servname provided, or not known",
        request=httpx.Request(
            "POST",
            "https://aiservice.voicesanj.ir/v1/audio/transcriptions",
        ),
    )

    code, detail, retryable = classify_failure(error, kind="asr")

    assert code == "asr_provider_network"
    assert "DNS" in detail
    assert retryable is True


def test_http_504_is_a_sanitized_retryable_timeout() -> None:
    error = classify_http(
        504,
        "<html><head><title>504 Gateway Time-out</title></head></html>",
        kind="llm",
    )

    assert error is not None
    assert error.code == "llm_provider_timeout"
    assert error.retryable is True
    assert "<html>" not in error.detail


def test_http_redirect_points_to_provider_configuration() -> None:
    error = classify_http(301, "<html>Moved Permanently</html>", kind="asr")
    assert error is not None
    assert error.code == "asr_provider_redirect"
    assert error.retryable is False
    assert "<html>" not in error.detail


def test_asr_model_contract_error_is_terminal_and_specific() -> None:
    error = classify_http(
        400,
        '{"detail":"Specify exactly one of model or models"}',
        kind="asr",
    )

    assert error is not None
    assert error.code == "asr_provider_model"
    assert error.retryable is False


def test_llm_extra_field_error_is_terminal_and_specific() -> None:
    error = classify_http(
        422,
        '{"detail":[{"msg":"Extra inputs are not permitted",'
        '"loc":["body","response_format"]}]}',
        kind="llm",
    )

    assert error is not None
    assert error.code == "llm_provider_request"
    assert error.retryable is False


def test_inspect_payload_raises_on_billing_json() -> None:
    with pytest.raises(ProviderError) as caught:
        inspect_payload({"error": {"message": "You have no remaining credit"}}, kind="asr")
    assert caught.value.code == "asr_provider_credit"
    assert caught.value.retryable is False


def test_successful_chat_content_may_contain_credit_words() -> None:
    inspect_payload(
        {"choices": [{"delta": {"content": "اعتبار قرارداد تأیید شد"}}]},
        kind="llm",
    )
