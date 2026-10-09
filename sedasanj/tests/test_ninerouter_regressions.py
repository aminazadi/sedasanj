from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.errors import ApiError
from app.models import PlatformSetting
from app.routers import admin
from app.schemas import NineRouterConnectionInput, SettingsUpdate
from app.services.aiservice_decision import AiServiceDecisionClient
from app.services.ninerouter import NineRouterClient
from app.services.platform_secrets import encrypt_secret
from app.services.provider_errors import ProviderError
from app.services.transcript_corrections import CorrectionClient
from worker_llm.client import LlamaClient, build_client


def settings(**updates):
    return Settings(environment="development").model_copy(
        update={
            "active_ai_provider": "ninerouter_direct",
            "llm_client": "ninerouter",
            "llama_server_urls": "https://router.test",
            "ninerouter_base_url": "https://router.test",
            "ninerouter_api_key": "arbitrary-private-key",
            "openai_api_key": "arbitrary-private-key",
            "ninerouter_connect_timeout_seconds": 1,
            "ninerouter_read_timeout_seconds": 10,
            "voicesanj_base_url": None,
            "voicesanj_api_key": None,
            **updates,
        }
    )


class Session:
    def __init__(self, values=None):
        self.rows = {
            key: PlatformSetting(key=key, value=value) for key, value in (values or {}).items()
        }

    async def get(self, model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.key] = row

    async def flush(self):
        pass


@pytest.fixture
def configured(monkeypatch):
    runtime = settings(platform_secrets_key=Fernet.generate_key().decode())
    monkeypatch.setattr("app.services.platform_secrets.get_settings", lambda: runtime)
    monkeypatch.setattr(admin, "get_settings", lambda: runtime)
    monkeypatch.setattr(admin.audit, "record", AsyncMock())
    monkeypatch.setattr(admin, "client_ip", lambda _: "127.0.0.1")

    async def view(session):
        return {key: row.value for key, row in session.rows.items()}

    monkeypatch.setattr(admin, "settings_public_view", view)
    return runtime


@pytest.mark.asyncio
async def test_save_connection_without_aiservice(configured):
    session = Session()
    result = await admin.update_platform_settings(
        SettingsUpdate(
            ninerouter_base_url="https://router.test/", ninerouter_api_key="arbitrary-private-key"
        ),
        None,
        SimpleNamespace(id=uuid4()),
        session,
    )
    assert result["ninerouter_base_url"] == "https://router.test"
    assert result["ninerouter_api_key"].startswith("fernet:v1:")
    assert "arbitrary-private-key" not in result["ninerouter_api_key"]
    before = result["ninerouter_api_key"]
    await admin.update_platform_settings(
        SettingsUpdate(ninerouter_api_key=""), None, SimpleNamespace(id=uuid4()), session
    )
    assert session.rows["ninerouter_api_key"].value == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability", ["asr", "analysis", "assistant", "correction", "decision", "embedding"]
)
async def test_cannot_clear_active_direct_model(configured, capability):
    provider = "asr_ai_provider" if capability == "asr" else f"{capability}_provider"
    model = (
        f"ninerouter_{capability}_model"
        if capability != "correction"
        else "ninerouter_correction_models"
    )
    session = Session(
        {
            provider: "ninerouter_direct",
            model: '["model"]' if capability == "correction" else "model",
            "ninerouter_api_key": encrypt_secret("private"),
        }
    )
    with pytest.raises(ApiError):
        await admin.update_platform_settings(
            SettingsUpdate(**{model: [] if capability == "correction" else "  "}),
            None,
            SimpleNamespace(id=uuid4()),
            session,
        )
    assert session.rows[model].value.strip()


@pytest.mark.asyncio
async def test_preview_uses_unsaved_connection_without_persisting(configured):
    session = Session(
        {"ninerouter_base_url": "https://old.test", "ninerouter_api_key": encrypt_secret("old-key")}
    )
    runtime = await admin._ninerouter_runtime(
        session,
        NineRouterConnectionInput(
            ninerouter_base_url="https://new.test/",
            ninerouter_api_key="Bearer new-key",
            ninerouter_read_timeout_seconds=60,
        ),
    )
    assert runtime.ninerouter_api_key == "new-key"
    assert runtime.ninerouter_base_url == "https://new.test"
    assert runtime.ninerouter_read_timeout_seconds == 60
    assert session.rows["ninerouter_base_url"].value == "https://old.test"
    reused = await admin._ninerouter_runtime(
        session, NineRouterConnectionInput(ninerouter_api_key="")
    )
    assert reused.ninerouter_api_key == "old-key"


@pytest.mark.asyncio
async def test_missing_configuration_is_api_error(configured):
    # Do not inherit a test fixture API key when no persisted key exists.
    configured.ninerouter_api_key = None
    with pytest.raises(ApiError):
        await admin._ninerouter_models(Session(), "chat")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]},
    ],
)
async def test_malformed_chat_is_controlled_error(payload):
    client = NineRouterClient(settings())
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(ProviderError):
            await client.chat({"model": "model"})
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("vector", [[], [True], ["0.1"], [float("inf")], [float("nan")]])
async def test_invalid_embedding_is_controlled_error(vector):
    client = NineRouterClient(settings())
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=json.dumps({"data": [{"embedding": vector}]}))
        )
    )
    try:
        with pytest.raises(ProviderError):
            await client.embedding(model="model", content="text")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_non_json_provider_response_is_controlled():
    client = NineRouterClient(settings())
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html>proxy error</html>")
        )
    )
    try:
        with pytest.raises(ProviderError):
            await client.list_models("chat")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_decision_is_independent_of_aiservice():
    client = AiServiceDecisionClient(settings(), request_namespace="test")
    answer = {
        "type": "score",
        "answer": 1,
        "confidence": 0.9,
        "margin": 0.8,
        "abstained": False,
        "probabilities": {"1": 0.9},
        "evidence": ["source"],
    }
    await client._ninerouter._client.aclose()
    client._ninerouter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"version": "v1", "answers": {"q": answer}})
                            }
                        }
                    ]
                },
            )
        )
    )
    try:
        result = await client.decide(
            model="decision",
            state="source",
            questions={"q": {"type": "score", "criteria": ["bad", "good"]}},
        )
        assert result["answers"]["q"]["answer"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_correction_uses_both_admin_prompts():
    client = CorrectionClient(settings(ninerouter_direct_prompt="extra instruction"))

    def respond(request):
        system = json.loads(request.content)["messages"][0]["content"]
        assert "base instruction" in system and "extra instruction" in system
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"segments": [], "uncertain_items": []}'}}]},
        )

    await client._ninerouter._client.aclose()
    client._ninerouter._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        assert (await client.complete_direct([], "base instruction", model="correction"))[
            "model"
        ] == "correction"
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["analysis", "chat"])
async def test_llm_routes_with_direct_model_and_prompt(purpose):
    client = build_client(
        settings(llm_model="chosen", ninerouter_direct_prompt="admin prompt"), purpose=purpose
    )
    assert isinstance(client, LlamaClient)

    def respond(request):
        assert request.url == "https://router.test/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "chosen"
        assert "admin prompt" in body["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})

    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        assert await client.complete("system", "user") == "answer"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_stream_interruption_does_not_replay_partial_answer():
    attempts = 0

    def respond(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
            headers={"Content-Type": "text/event-stream"},
        )

    client = LlamaClient(settings())
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    chunks = []
    try:
        with pytest.raises(ProviderError):
            async for chunk in client.stream("system", "user"):
                chunks.append(chunk)
    finally:
        await client.close()
    assert chunks == ["partial"]
    assert attempts == 1
