"""Shared webhook transport: secret storage, signing headers and one guarded POST.

Used by the notify worker and by the API's test-ping and redeliver endpoints so every delivery
is signed, SSRF-checked and measured the same way.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from app.errors import ApiError
from app.models import Webhook
from app.security import sign_webhook
from app.services import platform_secrets
from app.services.urlguard import assert_safe_webhook_url_async

PAYLOAD_VERSION = 1
# While a rotated secret is still accepted, deliveries carry a second signature made with it.
ROTATION_GRACE = timedelta(hours=24)
ERROR_TEXT_LIMIT = 300

EVENT_CATALOG: dict[str, str] = {
    "call.complete": "تحلیل تماس کامل شد؛ خلاصه، احساس، intent و نتیجه فروش در data است.",
    "call.failed": "پردازش تماس با خطا متوقف شد؛ error_code در data است.",
    "sales.insight": "بعد از call.complete فقط وقتی تحلیل فروش وجود دارد ارسال می‌شود.",
    "balance.low": "اعتبار سازمان از آستانه کمتر شد؛ balance_seconds و balance_toman در data است.",
    "webhook.ping": "رویداد آزمایشی که با دکمهٔ «تست» یا POST /v1/webhooks/{id}/test ارسال می‌شود.",
}
SUBSCRIBABLE_EVENTS = ("call.complete", "call.failed", "balance.low", "sales.insight")


@dataclass(frozen=True)
class DeliveryResult:
    status_code: int | None
    error: str | None
    latency_ms: int

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None


def seal_secret(value: str) -> str:
    """Encrypt when the platform key exists; fall back to the plain value in development."""
    if platform_secrets.secret_storage_error():
        return value
    return platform_secrets.encrypt_secret(value)


def open_secret(value: str) -> str:
    """Read both encrypted values and the plain ones stored before encryption existed."""
    if value.startswith(platform_secrets.PREFIX):
        return platform_secrets.decrypt_secret(value)
    return value


def delivery_id_for(webhook_id: UUID, event: str, call_id: UUID | None) -> UUID:
    """Stable per webhook, event and call, so receivers can deduplicate retries."""
    return uuid5(NAMESPACE_URL, f"cbi-webhook:{webhook_id}:{event}:{call_id or 'none'}")


def build_ping(tenant_id: UUID) -> dict[str, Any]:
    return {
        "version": PAYLOAD_VERSION,
        "event": "webhook.ping",
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tenant_id": str(tenant_id),
        "call_id": None,
        "data": {"message": "ping"},
    }


def _short(text: str) -> str:
    return text[:ERROR_TEXT_LIMIT]


async def post(
    client: httpx.AsyncClient,
    hook: Webhook,
    payload: dict[str, Any],
    *,
    delivery_id: UUID,
    attempt: int,
) -> DeliveryResult:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "X-CBI-Timestamp": timestamp,
        "X-CBI-Signature": sign_webhook(open_secret(hook.secret), timestamp, body),
        "X-CBI-Event": str(payload["event"]),
        "X-CBI-Delivery": str(delivery_id),
        "X-CBI-Attempt": str(attempt),
    }
    if (
        hook.secret_previous
        and hook.secret_rotated_at is not None
        and datetime.now(UTC) - hook.secret_rotated_at < ROTATION_GRACE
    ):
        headers["X-CBI-Signature-Previous"] = sign_webhook(
            open_secret(hook.secret_previous), timestamp, body
        )
    started = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        # Re-checked at delivery time because DNS can be repointed after registration (§12).
        await assert_safe_webhook_url_async(hook.url)
        response = await client.post(hook.url, content=body, headers=headers)
    except ApiError as exc:
        return DeliveryResult(None, _short(exc.message), elapsed())
    except httpx.HTTPError as exc:
        # Only the exception class: its text can carry the target URL and its tokens.
        return DeliveryResult(None, type(exc).__name__, elapsed())
    error = None if response.is_success else _short(f"HTTP {response.status_code}")
    return DeliveryResult(response.status_code, error, elapsed())
