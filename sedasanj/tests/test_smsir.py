from __future__ import annotations

import json

import httpx
import pytest

from app.errors import ApiError
from app.services import smsir
from app.services.demo_settings import DemoSettings, public_view


@pytest.mark.parametrize("status,body", [(200, {"status": 0}), (400, {"status": 100}), (200, [])])
async def test_smsir_rejects_provider_failures(monkeypatch, status, body) -> None:
    client_class = httpx.AsyncClient
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        smsir.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(handle),
            **kwargs,
        ),
    )
    with pytest.raises(ApiError):
        await smsir.send_verification(
            "09121234567",
            "123456",
            DemoSettings(
                smsir_api_key="test-only-key",
                smsir_template_id=42,
            ),
        )
    assert len(calls) == 1


async def test_smsir_uses_service_template_and_exact_parameter(monkeypatch) -> None:
    client_class = httpx.AsyncClient
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(200, json={"status": 1, "data": {"messageId": 123}})

    monkeypatch.setattr(
        smsir.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(handle),
            **kwargs,
        ),
    )
    await smsir.send_verification(
        "09121234567",
        "012345",
        DemoSettings(
            smsir_api_key="test-only-key",
            smsir_template_id=42,
            smsir_code_parameter="Code",
        ),
    )
    assert len(captured) == 1
    assert str(captured[0].url) == "https://api.sms.ir/v1/send/verify"
    assert captured[0].headers["X-API-KEY"] == "test-only-key"
    assert json.loads(captured[0].content) == {
        "mobile": "09121234567",
        "templateId": 42,
        "parameters": [{"name": "Code", "value": "012345"}],
    }


def test_demo_settings_never_return_api_key_or_storage_key() -> None:
    result = public_view(
        DemoSettings(smsir_api_key="private-test-value", prompt_object_key="private.wav")
    )
    assert "smsir_api_key" not in result
    assert "prompt_object_key" not in result
    assert result["smsir_api_key_configured"] is True
    assert result["prompt_configured"] is True


async def test_smsir_timeout_is_not_automatically_retried(monkeypatch) -> None:
    client_class = httpx.AsyncClient
    attempts = []

    def handle(request):
        attempts.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    monkeypatch.setattr(
        smsir.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(handle),
            **kwargs,
        ),
    )
    with pytest.raises(ApiError):
        await smsir.send_verification(
            "09121234567",
            "123456",
            DemoSettings(
                smsir_api_key="test-only-key",
                smsir_template_id=42,
            ),
        )
    assert len(attempts) == 1
