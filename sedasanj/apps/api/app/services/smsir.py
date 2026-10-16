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
        if get_settings().environment == "development":
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
