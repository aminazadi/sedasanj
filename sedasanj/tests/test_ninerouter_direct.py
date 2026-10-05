from __future__ import annotations

import json
import wave
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.services.ninerouter import NineRouterClient, retry_json_chat
from app.services.platform_secrets import decrypt_secret, encrypt_secret
from app.services.provider_errors import ProviderError


def _settings(**updates: object) -> Settings:
    return Settings(
        environment="development",
        ninerouter_base_url="https://router.test",
        ninerouter_api_key="9r_super-secret",
        ninerouter_connect_timeout_seconds=1,
        ninerouter_read_timeout_seconds=10,
    ).model_copy(update=updates)


def _client(handler: httpx.MockTransport) -> NineRouterClient:
    client = NineRouterClient(_settings())
    client._client = httpx.AsyncClient(  # noqa: SLF001 - contract-test transport
        transport=handler,
        headers=client._headers,  # noqa: SLF001 - preserve production headers
    )
    return client


def _wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 160)


def test_platform_secret_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        "app.services.platform_secrets.get_settings",
        lambda: _settings(platform_secrets_key=key),
    )
    encrypted = encrypt_secret("9r_private")
    assert encrypted.startswith("fernet:v1:")
    assert "9r_private" not in encrypted
    assert decrypt_secret(encrypted) == "9r_private"


def test_platform_secret_requires_valid_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.platform_secrets.get_settings",
        lambda: _settings(platform_secrets_key=None),
    )
    with pytest.raises(RuntimeError, match="PLATFORM_SECRETS_KEY"):
        encrypt_secret("9r_private")


@pytest.mark.asyncio
async def test_health_and_model_discovery_use_direct_contracts() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer 9r_super-secret"
        paths.append(request.url.path)
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "version": "0.5.2"})
        return httpx.Response(200, json={"data": [{"id": request.url.path}]})

    client = _client(httpx.MockTransport(handler))
    try:
        assert (await client.health())["status"] == "ok"
        assert (await client.list_models("chat"))[0]["id"] == "/v1/models"
        assert (await client.list_models("stt"))[0]["id"] == "/v1/models/stt"
        assert (await client.list_models("embedding"))[0]["id"] == "/v1/models/embedding"
    finally:
        await client.close()
    assert paths == ["/api/health", "/v1/models", "/v1/models/stt", "/v1/models/embedding"]


@pytest.mark.asyncio
async def test_health_rejects_known_unsafe_version() -> None:
    client = _client(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ok", "version": "0.5.1"})
        )
    )
    try:
        with pytest.raises(ProviderError, match="0.5.2") as caught:
            await client.health()
    finally:
        await client.close()
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_chat_embedding_and_multipart_asr_contract(tmp_path: Path) -> None:
    formats: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            assert body["model"] == "chat-model"
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
        if request.url.path == "/v1/embeddings":
            return httpx.Response(200, json={"data": [{"embedding": [0.25, 0.75]}]})
        content = await request.aread()
        formats.append(
            "json" if b'name="response_format"\r\n\r\njson' in content else "verbose_json"
        )
        assert b'name="file"; filename="sample.wav"' in content
        return httpx.Response(200, json={"text": "سلام"})

    audio = tmp_path / "sample.wav"
    _wav(audio)
    client = _client(httpx.MockTransport(handler))
    try:
        chat = await client.chat({"model": "chat-model", "messages": []})
        assert chat["choices"][0]["message"]["content"] == "{}"
        assert await client.embedding(model="embedding-model", content="متن") == [0.25, 0.75]
        assert (await client.transcribe(audio, model="gpt-4o-mini-transcribe"))["text"] == "سلام"
        assert (await client.transcribe(audio, model="whisper-large-v3"))["text"] == "سلام"
    finally:
        await client.close()
    assert formats == ["json", "verbose_json"]


@pytest.mark.asyncio
async def test_retry_stays_on_ninerouter_and_redacts_secret() -> None:
    attempts = 0

    def retry_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, text="Bearer 9r_super-secret")

    client = _client(httpx.MockTransport(retry_handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await client.health()
    finally:
        await client.close()
    assert attempts == 3
    assert "9r_super-secret" not in caught.value.detail

    auth_attempts = 0

    def auth_handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_attempts
        auth_attempts += 1
        return httpx.Response(401, text="invalid 9r_super-secret")

    client = _client(httpx.MockTransport(auth_handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await client.health()
    finally:
        await client.close()
    assert auth_attempts == 1
    assert "9r_super-secret" not in caught.value.detail


@pytest.mark.asyncio
async def test_json_chat_repairs_only_once() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        content = "not-json" if attempts == 1 else '{"answers": {}}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = _client(httpx.MockTransport(handler))
    try:
        result = await retry_json_chat(
            client,
            model="chat-model",
            messages=[{"role": "user", "content": "return json"}],
            max_tokens=100,
        )
    finally:
        await client.close()
    assert result == {"answers": {}}
    assert attempts == 2


@pytest.mark.asyncio
async def test_each_capability_routes_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import platform as platform_service

    values = {
        "ninerouter_api_key": "encrypted-value",
        "ninerouter_base_url": "https://router.test/",
        "asr_ai_provider": "ninerouter_direct",
        "analysis_provider": "ninerouter_direct",
        "assistant_provider": "ninerouter_direct",
        "correction_provider": "ninerouter_direct",
        "decision_provider": "ninerouter_direct",
        "embedding_provider": "ninerouter_direct",
        "ninerouter_asr_model": "stt-model",
        "ninerouter_analysis_model": "analysis-model",
        "ninerouter_assistant_model": "assistant-model",
        "ninerouter_correction_models": '["correct-1", "correct-2"]',
        "ninerouter_decision_model": "decision-model",
        "ninerouter_embedding_model": "embedding-model",
    }
    rows = [type("Row", (), {"key": key, "value": value})() for key, value in values.items()]

    class Result:
        def scalars(self) -> list[object]:
            return rows

    class Session:
        async def execute(self, statement: object) -> Result:
            return Result()

    monkeypatch.setattr(platform_service, "get_settings", lambda: _settings())
    monkeypatch.setattr(platform_service, "decrypt_secret", lambda value: "9r_direct")
    expected = {
        "asr": "stt-model",
        "analysis": "analysis-model",
        "assistant": "assistant-model",
        "correction": "correct-1",
        "decision": "decision-model",
        "embedding": "embedding-model",
    }
    for capability, model in expected.items():
        runtime = await platform_service.resolve_provider_settings(  # type: ignore[arg-type]
            Session(), capability=capability
        )
        assert runtime.active_ai_provider == "ninerouter_direct"
        assert runtime.ninerouter_api_key == "9r_direct"
        assert runtime.ninerouter_base_url == "https://router.test"
        if capability == "asr":
            assert runtime.whisper_model == model
        elif capability == "correction":
            assert runtime.correction_text_models[0] == model
        elif capability == "decision":
            assert runtime.decision_model == model
        elif capability == "embedding":
            assert runtime.embedding_model == model
        else:
            assert runtime.llm_model == model

    aiservice = await platform_service.resolve_provider_settings(  # type: ignore[arg-type]
        Session(), capability="analysis", provider_override="aiservice"
    )
    assert aiservice.active_ai_provider == "aiservice"
    assert aiservice.llm_client == "voicesanj"
