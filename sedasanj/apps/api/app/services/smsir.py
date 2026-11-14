from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.db import control_session_scope
from app.errors import ApiError
from app.services.demo_settings import DemoSettings, load

logger = logging.getLogger(__name__)


async def send_verification(mobile: str, code: str, settings: DemoSettings | None = None) -> None:
    if settings is None:
        async with control_session_scope() as session:
            settings = await load(session)
    if not settings.smsir_api_key or not settings.smsir_template_id:
        if get_settings().dev_otp_visible:
            logger.warning("Development phone OTP for %s: %s", mobile, code)
            return
        raise ApiError("invalid_request", "تنظیمات ارسال کد تأیید پیامکی تکمیل نشده است.")
    body = {
        "mobile": mobile,
        "templateId": settings.smsir_template_id,
        "parameters": [{"name": settings.smsir_code_parameter, "value": code}],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.post(
                f"{settings.smsir_base_url.rstrip('/')}/send/verify",
                headers={"X-API-KEY": settings.smsir_api_key, "Content-Type": "application/json"},
                json=body,
            )
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ApiError("internal", "ارسال پیامک انجام نشد؛ کمی بعد دوباره تلاش کنید.") from exc
    if not response.is_success or not isinstance(result, dict) or result.get("status") != 1:
        raise ApiError(
            "internal", "سرویس پیامک درخواست را نپذیرفت؛ تنظیمات قالب و اعتبار را بررسی کنید."
        )


class SmsDeliveryError(Exception):
    """A template send that did not go through.

    ``retryable`` is only true when the provider definitely did not accept the message (5xx,
    429).  A timeout is ``unknown``: the message may already be accepted, so it is never retried.
    """

    def __init__(self, message: str, *, retryable: bool = False, unknown: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.unknown = unknown


async def send_template(
    mobile: str,
    template_id: int,
    parameters: dict[str, str],
    settings: DemoSettings,
) -> None:
    """POST /send/verify with an approved service template and its named parameters."""
    if not settings.smsir_api_key:
        raise SmsDeliveryError("SMS.ir API key is not configured")
    body = {
        "mobile": mobile,
        "templateId": template_id,
        "parameters": [{"name": name, "value": value} for name, value in parameters.items()],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.post(
                f"{settings.smsir_base_url.rstrip('/')}/send/verify",
                headers={"X-API-KEY": settings.smsir_api_key, "Content-Type": "application/json"},
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise SmsDeliveryError("provider timeout", unknown=True) from exc
    except httpx.HTTPError as exc:
        raise SmsDeliveryError("provider unreachable", retryable=True) from exc
    if response.status_code >= 500 or response.status_code == 429:
        raise SmsDeliveryError(f"provider http {response.status_code}", retryable=True)
    try:
        result = response.json()
    except ValueError:
        result = None
    if not response.is_success or not isinstance(result, dict) or result.get("status") != 1:
        status = result.get("status") if isinstance(result, dict) else None
        raise SmsDeliveryError(
            f"provider rejected the message (http {response.status_code}, status {status})"
        )
