---
name: sedasanj-pipeline-failure-classification
description: Classify processing-pipeline failures into stable codes with retry semantics and separate customer-safe and operator messages. Use when editing classify_failure or provider/job error handling.
---

# Pipeline failure classification

## Current code (verified)

`classify_failure(exc, *, kind)` in `sedasanj/apps/api/app/services/provider_errors.py` returns `(error_code, error_detail, retryable_override)`. It handles `ProviderError`, `AudioPreprocessingError`, `TimeoutError`, `httpx.NetworkError`, then falls back to text matching on `repr(exc)` and finally `f"{kind}_failed"` with `repr(exc)[:2000]`.

## Rules for changes

1. Prefer explicit codes raised at the source (`ProviderError(code, detail, retryable=…)`) over regex on `repr(exc)`. Add a new text marker only as a temporary bridge, with a test.
2. Every classification states `retryable` explicitly; `None` (unknown) must be a deliberate choice.
3. Two messages: customer-safe (Persian, actionable, no internals) and operator detail (sanitized with `sanitize_detail` in `app/services/processing_events.py`). Remove raw `repr(exc)` and echoed input from anything a customer can see.
4. New code ⇒ add to the error-code docs/help (`sedasanj-error-codes`) and a test; add a completeness test that every emitted code has a message and a retry decision.
5. Silent stalls and timeouts get their own codes rather than the generic `*_failed`.

## Verify

`cd sedasanj && pytest tests/test_provider_errors.py tests/test_pipeline_retry.py tests/test_transcription_retry.py && mypy apps`.
