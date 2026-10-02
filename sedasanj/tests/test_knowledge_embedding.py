from __future__ import annotations

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
