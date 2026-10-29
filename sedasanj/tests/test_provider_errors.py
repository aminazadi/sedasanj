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
    assert retryable is False
    assert "متن" in detail
    assert "GapGPT" not in detail


def test_missing_provider_transcription_text_is_terminal() -> None:
    code, detail, retryable = classify_failure(
        RuntimeError("9Router transcription response did not contain text"), kind="asr"
    )

    assert code == "asr_empty_transcript"
    assert retryable is False
    assert "متن" in detail


def test_empty_detected_speech_regions_are_terminal() -> None:
    code, _detail, retryable = classify_failure(
        RuntimeError("9Router returned no text for detected speech regions"), kind="asr"
    )

    assert code == "asr_empty_transcript"
    assert retryable is False


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


def test_asr_model_contract_error_preserves_safe_provider_detail() -> None:
    error = classify_http(
        400,
        '{"detail":"ASR model openai/whisper-1 is not available; api_key=secret-value"}',
        kind="asr",
    )

    assert error is not None
    assert "openai/whisper-1" in error.detail
    assert "secret-value" not in error.detail
    assert "[redacted]" in error.detail


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


def test_tenant_credit_error_is_not_reported_as_provider_credit() -> None:
    from app.errors import ApiError
    from app.services.provider_errors import classify_failure

    code, detail, retryable = classify_failure(
        ApiError("insufficient_credit", "not enough minutes"), kind="llm"
    )
    assert code == "insufficient_credit" and "VoiceSanj" not in detail
    assert isinstance(retryable, bool)


def test_silence_is_a_final_no_speech_error() -> None:
    from app.services.provider_errors import classify_failure

    for message in (
        "ASR produced no text",
        "voicesanj task failed: NoSpeechDetectedError: nothing",
    ):
        code, _, retryable = classify_failure(RuntimeError(message), kind="asr")
        assert code == "asr_no_speech" and retryable is False, message


def test_httpx_timeouts_are_retryable_provider_timeouts() -> None:
    import httpx

    from app.services.provider_errors import classify_failure

    for exc in (httpx.ReadTimeout("x"), httpx.ConnectTimeout("x")):
        assert classify_failure(exc, kind="asr")[::2] == ("asr_provider_timeout", True)


def test_unknown_failures_do_not_leak_repr_or_secrets() -> None:
    from app.services.provider_errors import classify_failure

    code, detail, _ = classify_failure(
        RuntimeError("boom at http://minio:9000 Bearer abcdefghijklmnop12345"), kind="asr"
    )
    assert code == "asr_failed" and "abcdefghijklmnop12345" not in detail
    assert detail.startswith("RuntimeError:")
