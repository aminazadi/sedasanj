from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.services.provider_errors import ProviderError
from worker_asr.engine import WhisperEngine, build_engine
from worker_llm.client import LlamaClient


def _openai_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "development",
        "asr_engine": "whisper",
        "llm_client": "llama",
        "llama_server_urls": "https://llm.example.test",
        "llm_model": "gpt-4o-mini",
        "whisper_model": "whisper-1",
        "openai_api_key": "sk-test",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_build_engine_selects_whisper() -> None:
    engine = build_engine(_openai_settings())
    assert isinstance(engine, WhisperEngine)
    assert engine.model_name == "whisper-1"


async def test_whisper_engine_parses_verbose_segments(wav_file) -> None:
    path = wav_file(seconds=1.0)
    engine = WhisperEngine(_openai_settings())

    class Response:
        status_code = 200
        text = '{"text": "سلام"}'

        def json(self) -> dict[str, object]:
            return {
                "text": "سلام",
                "segments": [{"start": 0.0, "end": 0.8, "text": " سلام "}],
            }

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self, url: str, headers: dict[str, str], files: object, data: dict[str, str]
        ):
            assert url == "https://llm.example.test/v1/audio/transcriptions"
            assert headers["Authorization"] == "Bearer sk-test"
            assert data["language"] == "fa"
            assert data["model"] == "whisper-1"
            assert "prompt" not in data
            return Response()

    with patch("worker_asr.engine.httpx.AsyncClient", return_value=FakeClient()):
        rows = await engine.transcribe(path)
    assert rows[0].text == "سلام"
    assert rows[0].t_end_ms == 800


async def test_whisper_engine_prefers_admin_asr_endpoint_and_key(wav_file) -> None:
    path = wav_file(seconds=1.0)
    engine = WhisperEngine(
        _openai_settings(
            asr_provider_base_url="https://router.sedasanj.ir",
            asr_provider_api_key="router-key",
        )
    )

    class Response:
        status_code = 200
        text = '{"text": "سلام"}'

        def json(self) -> dict[str, str]:
            return {"text": "سلام"}

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self, url: str, headers: dict[str, str], files: object, data: dict[str, str]
        ) -> Response:
            assert url == "https://router.sedasanj.ir/v1/audio/transcriptions"
            assert headers["Authorization"] == "Bearer router-key"
            assert data["model"] == "whisper-1"
            return Response()

    with patch("worker_asr.engine.httpx.AsyncClient", return_value=FakeClient()):
        rows = await engine.transcribe(path)

    assert rows[0].text == "سلام"


async def test_llama_client_sends_bearer_and_hits_chat_completions() -> None:
    client = LlamaClient(_openai_settings())
    captured: dict[str, object] = {}

    async def fake_post(url: str, json: dict[str, object]):
        captured["url"] = url
        captured["json"] = json

        class Response:
            status_code = 200
            text = '{"choices":[{"message":{"content":"{\\"summary\\": \\"ok\\"}"}}]}'

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "choices": [{"message": {"content": '{"summary": "ok"}'}}],
                    "usage": {"completion_tokens": 4},
                }

        return Response()

    client._client.post = fake_post  # type: ignore[method-assign]
    content = await client.complete("سیستم", "کاربر")
    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert client._client.headers["Authorization"] == "Bearer sk-test"
    body = captured["json"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-4o-mini"
    assert body["max_tokens"] == 1200
    assert content == '{"summary": "ok"}'
    await client.close()


async def test_llama_client_preserves_typed_504_error() -> None:
    client = LlamaClient(_openai_settings())

    class Response:
        status_code = 504
        text = "<html><title>504 Gateway Time-out</title></html>"

    client._client.post = AsyncMock(return_value=Response())  # type: ignore[method-assign]
    with pytest.raises(ProviderError) as caught:
        await client.complete("سیستم", "کاربر")

    assert client._client.post.await_count == 1
    assert caught.value.code == "llm_provider_timeout"
    assert "<html>" not in caught.value.detail
    await client.close()
