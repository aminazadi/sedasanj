from __future__ import annotations

import json
import re
from contextlib import suppress

import httpx

CREDIT_MARKERS = (
    "insufficient",
    "quota",
    "credit",
    "balance",
    "payment required",
    "payment_required",
    "billing hard limit",
    "out of credit",
    "no credit",
    "top up",
    "top-up",
    "اعتبار",
    "موجودی",
    "شارژ",
)
AUTH_MARKERS = (
    "invalid api key",
    "incorrect api key",
    "invalid_api_key",
    "authentication",
    "unauthorized",
    "کلید",
)


class ProviderError(RuntimeError):
    """Typed failure from VoiceSanj / OpenAI-compatible ASR or LLM HTTP APIs."""

    def __init__(self, code: str, detail: str, *, retryable: bool = True) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


def looks_like_credit(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CREDIT_MARKERS)


def looks_like_auth(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in AUTH_MARKERS)


def _body_snippet(body: str, limit: int = 240) -> str:
    compact = " ".join(body.split())
    redacted = re.sub(
        r"(?i)(bearer\s+|(?:api[_ -]?key|token)[\"'=:\s]+|sk-)[^\s,;\"}]+",
        r"\1[redacted]",
        compact,
    )
    return redacted[:limit]


def _error_detail(body: str) -> str:
    with suppress(TypeError, ValueError):
        payload = json.loads(body)
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("error")
            if isinstance(detail, str):
                return _body_snippet(detail, 300)
    return _body_snippet(body, 300)


def classify_http(status_code: int, body: str, *, kind: str) -> ProviderError | None:
    """Map a provider HTTP response to a stored job error, or None when it looks successful."""
    if 200 <= status_code < 300:
        payload: object = None
        with suppress(TypeError, ValueError):
            payload = json.loads(body)
        if looks_like_credit(body) and (
            not isinstance(payload, dict)
            or _has_error_field(payload)
            or not _has_success_field(payload)
        ):
            return _credit(kind, status_code, body)
        return None
    if status_code == 402 or looks_like_credit(body):
        return _credit(kind, status_code, body)
    if status_code in (301, 302, 307, 308):
        return ProviderError(
            f"{kind}_provider_redirect",
            "آدرس پایه سرویس هوش مصنوعی تغییر کرده است. آدرس HTTPS را در تنظیمات مدل پنل ادمین بررسی کنید.",
            retryable=False,
        )
    lowered = body.lower()
    if kind == "asr" and status_code in (400, 422) and any(
        marker in lowered
        for marker in (
            "model or models",
            "valid asr model",
            "asr model",
            "model ids",
            '"model"',
            '"models"',
        )
    ):
        provider_detail = _error_detail(body)
        suffix = f" جزئیات سرویس: {provider_detail}" if provider_detail else ""
        return ProviderError(
            "asr_provider_model",
            "شناسه مدل پیاده‌سازی صوت نامعتبر است یا فیلدهای model/models "
            "برخلاف قرارداد VoiceSanj ارسال شده‌اند. یک مدل ASR قابل‌اجرا انتخاب کنید."
            f"{suffix}",
            retryable=False,
        )
    if kind == "llm" and status_code in (400, 422) and any(
        marker in lowered
        for marker in (
            "extra inputs are not permitted",
            "response_format",
            "tool_choice",
            '"tools"',
            "max_completion_tokens",
        )
    ):
        return ProviderError(
            "llm_provider_request",
            "پارامترهای درخواست تحلیل متن با قرارداد VoiceSanj سازگار نیستند.",
            retryable=False,
        )
    if status_code in (401, 403) or looks_like_auth(body):
        return ProviderError(
            f"{kind}_provider_auth",
            "کلید API سرویس هوش مصنوعی نامعتبر است. "
            "کلید را در تنظیمات مدل پنل ادمین بررسی کنید.",
            retryable=False,
        )
    if status_code == 429:
        return ProviderError(
            f"{kind}_provider_rate",
            "سرویس هوش مصنوعی موقتاً شلوغ است یا سهمیه لحظه‌ای تمام شده. کمی بعد دوباره تلاش می‌شود.",
            retryable=True,
        )
    if status_code in (408, 502, 503, 504):
        return ProviderError(
            f"{kind}_provider_timeout",
            "پاسخ سرویس هوش مصنوعی در زمان مقرر آماده نشد. "
            "درخواست به‌صورت کنترل‌شده دوباره تلاش می‌شود.",
            retryable=True,
        )
    snippet = _body_snippet(body)
    extra = f" (HTTP {status_code}" + (f": {snippet}" if snippet else "") + ")"
    return ProviderError(
        f"{kind}_provider_error",
        f"سرویس هوش مصنوعی پاسخ نامعتبر داد.{extra}",
        retryable=status_code >= 500,
    )


def inspect_payload(payload: object, *, kind: str) -> None:
    """Raise when a 200 JSON body still reports a provider billing/auth failure."""
    blob = _payload_text(payload)
    if not blob:
        return
    if looks_like_credit(blob) and (
        _has_error_field(payload) or not _has_success_field(payload)
    ):
        raise _credit(kind, 200, blob)
    if looks_like_auth(blob) and _has_error_field(payload):
        raise ProviderError(
            f"{kind}_provider_auth",
            "کلید API سرویس هوش مصنوعی نامعتبر است. "
            "کلید را در تنظیمات مدل پنل ادمین بررسی کنید.",
            retryable=False,
        )


def classify_failure(exc: BaseException, *, kind: str) -> tuple[str, str, bool | None]:
    """Return (error_code, error_detail, retryable override) for job/call rows."""
    if isinstance(exc, ProviderError):
        return exc.code, exc.detail, exc.retryable
    # Import locally to avoid making generic provider classification depend on
    # ffmpeg/audio modules at import time.
    from app.services.audio import AudioPreprocessingError

    if isinstance(exc, AudioPreprocessingError):
        return (
            f"{kind}_preprocessing_failed",
            "پیش‌پردازش صوت با تنظیمات انتخاب‌شده ناموفق بود. "
            f"جزئیات فنی: {str(exc)[:1500]}",
            False,
        )
    if isinstance(exc, TimeoutError):
        return (
            f"{kind}_timeout",
            "زمان پردازش سرویس هوش مصنوعی بیش از حد مجاز شد. "
            "کار به‌صورت کنترل‌شده دوباره تلاش می‌شود.",
            True,
        )
    if isinstance(exc, httpx.NetworkError):
        return (
            f"{kind}_provider_network",
            "ارتباط شبکه یا DNS با سرویس هوش مصنوعی برقرار نشد. "
            "کار به‌صورت کنترل‌شده دوباره تلاش می‌شود.",
            True,
        )
    text = f"{exc!r} {exc}"
    if any(
        marker in text.lower()
        for marker in (
            "empty text",
            "empty transcript",
            "did not contain text",
            "returned no text",
        )
    ):
        return (
            f"{kind}_empty_transcript",
            "پیاده‌سازی گفتار متنی برنگرداند. فایل صوتی و وضعیت سرویس VoiceSanj را بررسی کنید.",
            False,
        )
    if looks_like_credit(text):
        credit = _credit(kind, 0, text)
        return credit.code, credit.detail, False
    return f"{kind}_failed", (repr(exc) or str(exc))[:2000], None


def _credit(kind: str, status_code: int, body: str) -> ProviderError:
    extra = f" (HTTP {status_code})" if status_code else ""
    snippet = _body_snippet(body)
    suffix = f"{extra}: {snippet}" if snippet and status_code else extra
    return ProviderError(
        f"{kind}_provider_credit",
        "اعتبار حساب سرویس VoiceSanj تمام شده است. حساب را شارژ کنید و کار را دوباره اجرا کنید."
        + suffix,
        retryable=False,
    )


def _payload_text(payload: object) -> str:
    if isinstance(payload, dict):
        try:
            return json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(payload)
    return str(payload) if payload is not None else ""


def _has_error_field(payload: object) -> bool:
    return isinstance(payload, dict) and any(
        key in payload for key in ("error", "error_code", "code")
    )


def _has_success_field(payload: object) -> bool:
    return isinstance(payload, dict) and any(
        key in payload
        for key in (
            "choices",
            "task_id",
            "text",
            "corrected_text",
            "summary",
            "result",
            "results",
        )
    )
