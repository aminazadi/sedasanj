from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.services.platform import normalize_provider_base_url
from app.services.provider_errors import ProviderError
from app.services.voicesanj import VoiceSanjClient, correct_transcript
from worker_asr.engine import VoiceSanjEngine, build_engine
from worker_llm.client import VoiceSanjChatClient, build_client


def _voicesanj_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "development",
        "asr_engine": "voicesanj",
        "llm_client": "voicesanj",
        "voicesanj_base_url": "http://aiservice.voicesanj.ir",
        "voicesanj_api_key": "test-key",
        "voicesanj_asr_model": "buzzasr-persian",
        "voicesanj_llm_model": "dorna-8b-q4_k_m",
        "voicesanj_poll_interval_seconds": 0.01,
        "voicesanj_poll_timeout_seconds": 5.0,
        "llama_server_urls": "http://unused:8081",
        "llm_model": "unused",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_build_engine_selects_voicesanj() -> None:
    engine = build_engine(_voicesanj_settings())
    assert isinstance(engine, VoiceSanjEngine)
    assert engine.model_name == "buzzasr-persian"


@pytest.mark.parametrize(
    ("url", "normalized"),
    [
        ("http://aiservice.voicesanj.ir", "https://aiservice.voicesanj.ir"),
        ("https://ai.example.com/", "https://ai.example.com"),
        ("http://192.168.1.20:8000", "http://192.168.1.20:8000"),
        ("http://[::1]:8000/", "http://[::1]:8000"),
    ],
)
def test_provider_base_url_accepts_domain_or_ip(url: str, normalized: str) -> None:
    assert normalize_provider_base_url(url) == normalized


@pytest.mark.parametrize(
    "url",
    [
        "https://ai.example.com/v1",
        "http://ai.example.com?token=secret",
        "http://user:secret@ai.example.com",
        "http://169.254.169.254",
        "http://ai.example.com:99999",
        "ftp://ai.example.com",
    ],
)
def test_provider_base_url_rejects_paths_and_invalid_hosts(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_provider_base_url(url)


def test_build_client_points_at_voicesanj() -> None:
    client = build_client(_voicesanj_settings(voicesanj_poll_timeout_seconds=1800.0))
    assert isinstance(client, VoiceSanjChatClient)
    assert client._base == "http://aiservice.voicesanj.ir"
    assert client._model == "dorna-8b-q4_k_m"
    assert client._poll_timeout == 1470.0
    assert client._client.headers["Authorization"] == "Bearer test-key"
    assert client._client.headers["User-Agent"] == "cbi-voice-analytics/httpx"
    assert client._client.headers["Accept"] == "application/json"


def test_voicesanj_chat_poll_timeout_stays_inside_analysis_deadline() -> None:
    client = VoiceSanjChatClient(
        _voicesanj_settings(
            analysis_timeout_seconds=600.0,
            voicesanj_poll_timeout_seconds=1800.0,
        )
    )
    assert client._poll_timeout == 570.0


async def test_voicesanj_chat_submits_polls_and_fetches_result() -> None:
    seen: dict[str, object] = {}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.method == "POST":
            seen.update(json.loads(request.content))
            seen["key"] = request.headers["Idempotency-Key"]
            return httpx.Response(202, json={"task_id": "t1", "status": "queued"})
        if request.url.path.endswith("/result"):
            return httpx.Response(
                200,
                json={
                    "object": "chat.completion",
                    "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                    "usage": {"completion_tokens": 4},
                },
            )
        return httpx.Response(200, json={"status": "succeeded"})

    client = VoiceSanjChatClient(_voicesanj_settings())
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test-key"},
    )
    try:
        content = await client.complete("سیستم", "کاربر")
    finally:
        await client.close()

    assert content == '{"summary":"ok"}'
    assert calls == ["/v1/chat/tasks", "/v1/tasks/t1", "/v1/tasks/t1/result"]
    assert isinstance(seen["key"], str)
    assert seen["max_tokens"] == 1200
    assert "response_format" not in seen
    assert "stream" not in seen


async def test_voicesanj_chat_does_not_duplicate_a_rejected_request() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            504,
            text="<html><title>504 Gateway Time-out</title></html>",
        )

    client = VoiceSanjChatClient(_voicesanj_settings())
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await client.complete("سیستم", "کاربر")
    finally:
        await client.close()

    assert requests == 1
    assert caught.value.code == "llm_provider_timeout"
    assert "<html>" not in caught.value.detail


async def test_voicesanj_chat_uses_same_idempotency_key_on_retry() -> None:
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            keys.append(request.headers["Idempotency-Key"])
            return httpx.Response(202, json={"task_id": "t1"})
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})
        return httpx.Response(200, json={"status": "succeeded"})

    for _ in range(2):
        client = VoiceSanjChatClient(_voicesanj_settings(), request_namespace="run-1")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            assert await client.complete("سیستم", "کاربر") == "done"
        finally:
            await client.close()
    assert keys[0] == keys[1]


async def test_voicesanj_chat_rejects_provider_result_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"task_id": "t1", "status_url": "http://127.0.0.1/admin"}
            )
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        assert request.url.path == "/v1/tasks/t1"
        return httpx.Response(200, json={"status": "succeeded"})

    client = VoiceSanjChatClient(_voicesanj_settings())
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await client.complete("system", "user") == "ok"
    finally:
        await client.close()


async def test_voicesanj_chat_polls_until_queued_task_succeeds() -> None:
    states = iter(["queued", "running", "succeeded"])
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(202, json={"task_id": "t1"})
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        return httpx.Response(200, json={"status": next(states)})

    client = VoiceSanjChatClient(_voicesanj_settings())
    client._poll_interval = 0
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await client.complete("system", "user") == "ok"
    finally:
        await client.close()
    assert paths.count("/v1/chat/tasks") == 1
    assert paths.count("/v1/tasks/t1") == 3
    assert paths[-1] == "/v1/tasks/t1/result"


async def test_voicesanj_chat_uses_configured_aiservice_ninerouter_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ninerouter/chat/completions"
        assert json.loads(request.content)["model"] == "chat-model"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "پاسخ"}}]},
        )

    client = VoiceSanjChatClient(
        _voicesanj_settings(
            aiservice_chat_path="/v1/ninerouter/chat/completions"
        ),
        purpose="chat",
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        content = await client.complete(
            "system", "user", json_object=False, model="chat-model"
        )
    finally:
        await client.close()

    assert content == "پاسخ"


async def test_voicesanj_analysis_uses_configured_aiservice_ninerouter_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ninerouter/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "analysis-model"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"sentiment":"neutral"}'}}]},
        )

    client = VoiceSanjChatClient(
        _voicesanj_settings(
            aiservice_analysis_path="/v1/ninerouter/chat/completions"
        ),
        purpose="analysis",
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        content = await client.complete(
            "system", "user", json_object=True, model="analysis-model"
        )
    finally:
        await client.close()

    assert content == '{"sentiment":"neutral"}'


async def test_voicesanj_chat_rejects_failed_task_without_fetching_result() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(202, json={"task_id": "t1"})
        return httpx.Response(200, json={"status": "failed", "error_code": "inference_error"})

    client = VoiceSanjChatClient(_voicesanj_settings())
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="inference_error") as caught:
            await client.complete("system", "user")
    finally:
        await client.close()
    assert caught.value.code == "llm_provider_task_failed"
    assert paths == ["/v1/chat/tasks", "/v1/tasks/t1"]


async def test_voicesanj_engine_polls_and_parses_segments(wav_file) -> None:
    path = wav_file(seconds=1.0)
    engine = VoiceSanjEngine(_voicesanj_settings())

    class SubmitResponse:
        status_code = 202
        text = '{"task_id":"t1","status":"queued"}'

        def json(self) -> dict[str, object]:
            return {
                "task_id": "t1",
                "status": "queued",
                "status_url": "/v1/tasks/t1",
                "result_url": "/v1/tasks/t1/result",
            }

    class StatusResponse:
        status_code = 200
        text = '{"status":"succeeded"}'

        def json(self) -> dict[str, object]:
            return {
                "task_id": "t1",
                "status": "succeeded",
                "status_url": "/v1/tasks/t1",
                "result_url": "/v1/tasks/t1/result",
            }

    class ResultResponse:
        status_code = 200
        text = '{"text":"سلام"}'

        def json(self) -> dict[str, object]:
            return {
                "text": "سلام",
                "language": "fa",
                "duration": 1.0,
                "duration_after_vad": 0.9,
                "model": "buzzasr-persian",
                "segments": [{"start": 0.0, "end": 0.7, "text": " سلام "}],
            }

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._gets = 0

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object):
            assert url.endswith("/v1/audio/transcriptions")
            assert kwargs["headers"]["Authorization"] == "Bearer test-key"
            assert kwargs["data"]["model"] == "buzzasr-persian"
            assert "prompt" not in kwargs["data"]
            assert set(kwargs["data"]) == {
                "model",
                "response_format",
                "beam_size",
                "vad_filter",
                "audio_encoding",
                "uncompressed_audio_bytes",
            }
            assert kwargs["data"]["audio_encoding"] == "gzip"
            assert kwargs["files"]["file"][2] == "application/gzip"
            assert set(kwargs["files"]) == {"file"}
            return SubmitResponse()

        async def get(self, url: str, **kwargs: object):
            self._gets += 1
            if url.endswith("/result"):
                return ResultResponse()
            return StatusResponse()

    with patch("app.services.voicesanj.httpx.AsyncClient", FakeClient):
        rows = await engine.transcribe(path)
    assert rows[0].text == "سلام"
    assert rows[0].t_end_ms == 700


async def test_voicesanj_allows_custom_asr_model(wav_file) -> None:
    client = VoiceSanjClient(_voicesanj_settings())

    class RejectedResponse:
        status_code = 400
        text = "{}"

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> RejectedResponse:
            assert url.endswith("/v1/audio/transcriptions")
            assert kwargs["data"]["model"] == "custom-asr"  # type: ignore[index]
            return RejectedResponse()

    with patch("app.services.voicesanj.httpx.AsyncClient", FakeClient):
        with pytest.raises(ProviderError):
            await client.transcribe(wav_file(seconds=1.0), model="  custom-asr  ")

    with pytest.raises(ProviderError) as caught:
        await client.transcribe(wav_file(seconds=1.0), model="   ")

    assert caught.value.code == "asr_provider_model"
    assert caught.value.retryable is False


async def test_correct_transcript_times_out() -> None:
    settings = _voicesanj_settings(voicesanj_correction_timeout_seconds=0.01)

    async def slow_correction(self: VoiceSanjClient, text: str, *, model: str | None = None) -> str:
        await asyncio.sleep(0.05)
        return "نباید برگردد"

    with (
        patch.object(VoiceSanjClient, "correct_text", slow_correction),
        pytest.raises(TimeoutError),
    ):
        await correct_transcript(settings, "متن خام")


async def test_correct_transcript_rejects_changed_speaker_structure() -> None:
    settings = _voicesanj_settings()

    async def broken_correction(
        self: VoiceSanjClient, text: str, *, model: str | None = None
    ) -> str:
        return "سلام. بفرمایید."

    source = "[caller 00:00] سلام\n[agent  00:01] بفرمایید"
    with (
        patch.object(VoiceSanjClient, "correct_text", broken_correction),
        pytest.raises(ValueError, match="speaker markers"),
    ):
        await correct_transcript(settings, source)


async def test_correct_text_uses_process_endpoint() -> None:
    client = VoiceSanjClient(_voicesanj_settings())

    class SubmitResponse:
        status_code = 202
        text = "{}"

        def json(self) -> dict[str, object]:
            return {
                "task_id": "c1",
                "status": "queued",
                "status_url": "/v1/tasks/c1",
                "result_url": "/v1/tasks/c1/result",
            }

    class StatusResponse:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, object]:
            return {
                "task_id": "c1",
                "status": "succeeded",
                "result_url": "/v1/tasks/c1/result",
            }

    class ResultResponse:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, object]:
            return {
                "model": "dorna-8b-q4_k_m",
                "operation": "correction",
                "corrected_text": "متن اصلاح‌شده",
                "uncertain_items": [],
            }

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object):
            assert url.endswith("/v1/text/process")
            assert kwargs["json"]["operation"] == "correction"
            return SubmitResponse()

        async def get(self, url: str, **kwargs: object):
            if url.endswith("/result"):
                return ResultResponse()
            return StatusResponse()

    with patch("app.services.voicesanj.httpx.AsyncClient", FakeClient):
        assert await client.correct_text("متن خام") == "متن اصلاح‌شده"


async def test_voicesanj_list_models() -> None:
    client = VoiceSanjClient(_voicesanj_settings())
    seen: list[str] = []

    class ModelsResponse:
        status_code = 200
        text = '{"data":[]}'

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {"id": "dorna-8b-q4_k_m", "kind": "llm"},
                    {
                        "id": "custom-llm",
                        "kind": "llm",
                        "owned_by": "openai",
                        "source": "9router",
                    },
                    {"id": "shenava-koochik-v1-5-rnnt", "kind": "asr"},
                    {"id": "embed-live", "kind": "embedding", "owned_by": "9router"},
                    {"id": "decision-live", "kind": "decision"},
                ]
            }

    class HealthResponse:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, object]:
            return {
                "installed_models": [
                    "dorna-8b-q4_k_m",
                    "shenava-koochik-v1-5-rnnt",
                    "decision-live",
                ]
            }

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> object:
            seen.append(url)
            if url.endswith("/v1/models"):
                assert kwargs["params"] == {"kind": "all"}
                return ModelsResponse()
            if url.endswith("/health"):
                return HealthResponse()
            raise AssertionError(url)

    with patch("app.services.voicesanj.httpx.AsyncClient", FakeClient):
        rows = await client.list_models()
    assert any(url.endswith("/v1/models") for url in seen)
    assert any(url.endswith("/health") for url in seen)
    assert not any("/api/models" in url for url in seen)
    by_id = {row["id"]: row for row in rows}
    assert by_id["shenava-koochik-v1-5-rnnt"]["kind"] == "asr"
    assert by_id["shenava-koochik-v1-5-rnnt"]["available"] is True
    assert by_id["dorna-8b-q4_k_m"]["kind"] == "llm"
    assert by_id["custom-llm"]["kind"] == "llm"
    assert by_id["custom-llm"]["available"] is True
    assert by_id["embed-live"]["kind"] == "embedding"
    assert by_id["embed-live"]["available"] is True
    assert by_id["decision-live"]["kind"] == "decision"
    assert "buzzasr-persian" not in by_id


async def test_voicesanj_validate_api_key_uses_user_endpoint() -> None:
    client = VoiceSanjClient(_voicesanj_settings())
    seen: list[str] = []

    class OkResponse:
        status_code = 200
        text = '{"data":[]}'

        def json(self) -> dict[str, object]:
            return {"data": []}

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> OkResponse:
            seen.append(url)
            assert kwargs["headers"]["Authorization"] == "Bearer test-key"
            return OkResponse()

    with patch("app.services.voicesanj.httpx.AsyncClient", FakeClient):
        await client.validate_api_key()
    assert seen == ["http://aiservice.voicesanj.ir/v1/models"]
