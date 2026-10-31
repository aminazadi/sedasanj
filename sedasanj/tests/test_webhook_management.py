from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from plan_routes import api_routes, dependency_calls
from pydantic import ValidationError

from app import deps
from app.config import get_settings
from app.schemas import WebhookCreate, WebhookUpdate
from app.security import sign_webhook
from app.services import webhook_delivery
from worker_notify import main as notify


def _hook(**extra: Any) -> Any:
    values: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "url": "https://hooks.example.com/in",
        "secret": "current-secret-value",
        "secret_previous": None,
        "secret_rotated_at": None,
        "events": ["call.complete"],
        "active": True,
        "consecutive_failures": 0,
    }
    values.update(extra)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(webhook_delivery, "assert_safe_webhook_url_async", AsyncMock())


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_every_webhook_route_is_org_admin_only() -> None:
    routes = [r for r in api_routes() if r.path.startswith("/v1/webhooks")]
    assert {r.path for r in routes} >= {
        "/v1/webhooks",
        "/v1/webhooks/events",
        "/v1/webhooks/{webhook_id}",
        "/v1/webhooks/{webhook_id}/rotate-secret",
        "/v1/webhooks/{webhook_id}/test",
        "/v1/webhooks/{webhook_id}/deliveries",
        "/v1/webhooks/deliveries/{delivery_row_id}/redeliver",
    }
    for route in routes:
        calls = dependency_calls(route.dependant)
        assert deps.current_user in calls, route.path
        assert deps.current_api_key not in calls, route.path


def test_secret_must_be_long_enough_and_events_are_validated() -> None:
    with pytest.raises(ValidationError):
        WebhookCreate(url="https://a.example.com", events=["call.complete"], secret="short")
    with pytest.raises(ValidationError):
        WebhookCreate(url="https://a.example.com", events=["webhook.ping"])
    with pytest.raises(ValidationError):
        WebhookUpdate(events=[])


async def test_post_signs_the_body_and_sends_a_stable_delivery_id() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = request.content
        return httpx.Response(204)

    hook = _hook()
    call_id = uuid4()
    delivery_id = webhook_delivery.delivery_id_for(hook.id, "call.complete", call_id)
    assert delivery_id == webhook_delivery.delivery_id_for(hook.id, "call.complete", call_id)
    assert delivery_id != webhook_delivery.delivery_id_for(hook.id, "call.failed", call_id)

    payload = {"version": 1, "event": "call.complete", "data": {"summary": "سلام"}}
    async with _client(handler) as client:
        result = await webhook_delivery.post(
            client, hook, payload, delivery_id=delivery_id, attempt=2
        )

    headers = seen["headers"]
    assert result.ok and result.status_code == 204
    assert headers["x-cbi-delivery"] == str(delivery_id)
    assert headers["x-cbi-attempt"] == "2"
    assert headers["x-cbi-event"] == "call.complete"
    assert headers["x-cbi-signature"] == sign_webhook(
        hook.secret, headers["x-cbi-timestamp"], seen["body"]
    )
    assert "x-cbi-signature-previous" not in headers


async def test_previous_secret_signs_only_inside_the_rotation_window() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200)

    payload = {"event": "webhook.ping"}
    fresh = _hook(secret_previous="old-secret-value", secret_rotated_at=datetime.now(UTC))
    stale = _hook(
        secret_previous="old-secret-value",
        secret_rotated_at=datetime.now(UTC) - timedelta(hours=25),
    )
    async with _client(handler) as client:
        for hook in (fresh, stale):
            await webhook_delivery.post(client, hook, payload, delivery_id=uuid4(), attempt=1)

    assert "x-cbi-signature-previous" in seen[0]
    assert seen[0]["x-cbi-signature-previous"] == sign_webhook(
        "old-secret-value", seen[0]["x-cbi-timestamp"], b'{"event":"webhook.ping"}'
    )
    assert "x-cbi-signature-previous" not in seen[1]


async def test_failures_are_reported_without_leaking_urls_or_bodies() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect to https://hooks.example.com/in?token=abc failed")

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="secret internal stack trace")

    async with _client(refuse) as client:
        refused = await webhook_delivery.post(
            client, _hook(), {"event": "x"}, delivery_id=uuid4(), attempt=1
        )
    async with _client(server_error) as client:
        failed = await webhook_delivery.post(
            client, _hook(), {"event": "x"}, delivery_id=uuid4(), attempt=1
        )

    assert refused.status_code is None and refused.error == "ConnectError"
    assert "token" not in (refused.error or "")
    assert failed.status_code == 500 and failed.error == "HTTP 500"
    assert not refused.ok and not failed.ok


def test_secret_storage_round_trips_and_reads_legacy_plaintext(monkeypatch) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setattr(get_settings(), "platform_secrets_key", Fernet.generate_key().decode())
    sealed = webhook_delivery.seal_secret("my-webhook-secret-1234")
    assert sealed != "my-webhook-secret-1234" and sealed.startswith("fernet:v1:")
    assert webhook_delivery.open_secret(sealed) == "my-webhook-secret-1234"
    assert webhook_delivery.open_secret("legacy-plaintext-secret") == "legacy-plaintext-secret"


async def test_consecutive_failures_disable_the_webhook_and_notify(monkeypatch) -> None:
    hook = _hook(consecutive_failures=get_settings().webhook_auto_disable_failures - 1)
    row = SimpleNamespace(
        consecutive_failures=hook.consecutive_failures,
        active=True,
        disabled_at=None,
        disabled_reason=None,
    )

    @asynccontextmanager
    async def fake_scope(*args: Any, **kwargs: Any):
        yield SimpleNamespace(get=AsyncMock(return_value=row))

    notified = AsyncMock()
    monkeypatch.setattr(notify, "session_scope", fake_scope)
    monkeypatch.setattr(notify, "_notify_webhook_disabled", notified)

    await notify._track_outcome(hook.tenant_id, hook, ok=False)

    assert row.active is False and row.disabled_reason == "consecutive_failures"
    notified.assert_awaited_once()

    row.active, row.consecutive_failures = True, 3
    await notify._track_outcome(hook.tenant_id, hook, ok=True)
    assert row.consecutive_failures == 0 and row.active is True
