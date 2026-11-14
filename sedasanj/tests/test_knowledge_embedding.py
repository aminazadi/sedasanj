from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from app.services import knowledge


@pytest.mark.asyncio
async def test_embedding_falls_back_to_native_after_ninerouter_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/v1/ninerouter/embeddings":
            return httpx.Response(422, json={"detail": "unsupported embedding model"})
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.25, 0.75]}]},
        )

    @asynccontextmanager
    async def fake_session_scope(*args: object, **kwargs: object):
        yield object()

    async def fake_effective_models(session: object) -> dict[str, str]:
        return {
            "voicesanj_base_url": "https://aiservice.example",
            "api_key": "secret",
            "embedding_model": "local-embedding",
            "embedding_route": "ninerouter",
        }

    real_client = httpx.AsyncClient

    def client_factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(knowledge, "session_scope", fake_session_scope)
    monkeypatch.setattr(knowledge, "effective_models", fake_effective_models)
    monkeypatch.setattr(knowledge.httpx, "AsyncClient", client_factory)

    vector, model = await knowledge.embed("sample")

    assert vector == [0.25, 0.75]
    assert model == "local-embedding"
    assert requested_paths == ["/v1/ninerouter/embeddings", "/v1/embeddings"]


@pytest.mark.asyncio
async def test_embedding_does_not_fallback_for_non_contract_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(503, json={"detail": "unavailable"})

    @asynccontextmanager
    async def fake_session_scope(*args: object, **kwargs: object):
        yield object()

    async def fake_effective_models(session: object) -> dict[str, str]:
        return {
            "voicesanj_base_url": "https://aiservice.example",
            "api_key": "secret",
            "embedding_model": "local-embedding",
            "embedding_route": "ninerouter",
        }

    real_client = httpx.AsyncClient

    def client_factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(knowledge, "session_scope", fake_session_scope)
    monkeypatch.setattr(knowledge, "effective_models", fake_effective_models)
    monkeypatch.setattr(knowledge.httpx, "AsyncClient", client_factory)

    with pytest.raises(httpx.HTTPStatusError):
        await knowledge.embed("sample")

    assert requested_paths == ["/v1/ninerouter/embeddings"]


@pytest.mark.parametrize("reject_batch", [False, True])
async def test_chunk_embeddings_reuse_only_compatible_vectors_and_preserve_order(
    monkeypatch: pytest.MonkeyPatch, reject_batch: bool
) -> None:
    inputs = []
    settings_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        values = json.loads(request.content)["input"]
        inputs.append(values)
        if reject_batch and isinstance(values, list):
            return httpx.Response(422, json={"detail": "batch unsupported"})
        if isinstance(values, str):
            values = [values]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(len(value)), 1.0]}
                    for index, value in reversed(list(enumerate(values)))
                ]
            },
        )

    @asynccontextmanager
    async def fake_session_scope(*args: object, **kwargs: object):
        yield object()

    async def fake_effective_models(session: object) -> dict[str, str]:
        nonlocal settings_reads
        settings_reads += 1
        return {
            "voicesanj_base_url": "https://aiservice.example",
            "api_key": "secret",
            "embedding_model": "local-embedding",
            "embedding_route": "native",
        }

    real_client = httpx.AsyncClient
    monkeypatch.setattr(knowledge, "session_scope", fake_session_scope)
    monkeypatch.setattr(knowledge, "effective_models", fake_effective_models)
    monkeypatch.setattr(
        knowledge.httpx,
        "AsyncClient",
        lambda *args, **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )

    cached = {
        (hashlib.sha256(b"cached").hexdigest(), "local-embedding", "aiservice"): "[9,1]",
        (hashlib.sha256(b"one").hexdigest(), "previous-model", "aiservice"): "[9,1]",
        (hashlib.sha256(b"second").hexdigest(), "local-embedding", "other"): "[9,1]",
    }
    results, _error = await knowledge.embed_index_chunks(["one", "cached", "second", "one"], cached)

    assert settings_reads == 1
    assert inputs == ([["one", "second"], "one", "second"] if reject_batch else [["one", "second"]])
    assert results == [
        ([3.0, 1.0], "local-embedding"),
        ([9.0, 1.0], "local-embedding"),
        ([6.0, 1.0], "local-embedding"),
        ([3.0, 1.0], "local-embedding"),
    ]


@pytest.mark.asyncio
async def test_aiservice_embedding_reports_exact_tokens_to_the_usage_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "local-embedding",
                "data": [{"embedding": [0.25, 0.75]}],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            },
        )

    @asynccontextmanager
    async def fake_session_scope(*args: object, **kwargs: object):
        yield object()

    async def fake_effective_models(session: object) -> dict[str, str]:
        return {
            "voicesanj_base_url": "https://aiservice.example",
            "api_key": "secret",
            "embedding_model": "local-embedding",
            "embedding_route": "ninerouter",
        }

    async def fake_record(raw_usage: object, **kwargs: object) -> None:
        recorded.append({"usage": raw_usage, **kwargs})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(knowledge, "session_scope", fake_session_scope)
    monkeypatch.setattr(knowledge, "effective_models", fake_effective_models)
    monkeypatch.setattr(knowledge, "record_usage", fake_record)
    monkeypatch.setattr(
        knowledge.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)),
    )

    await knowledge.embed("sample")

    assert len(recorded) == 1
    assert recorded[0]["usage"] == {"prompt_tokens": 7, "total_tokens": 7}
    assert recorded[0]["feature"] == "embedding" and recorded[0]["provider"] == "aiservice"
