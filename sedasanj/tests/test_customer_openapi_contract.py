from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.errors import ApiError, install_error_handlers
from app.main import create_app
from app.services import ratelimit


async def _spec() -> dict[str, Any]:
    app = create_app()
    route = next(r for r in app.routes if getattr(r, "path", None) == "/v1/openapi/customer.json")
    return json.loads((await route.endpoint()).body)


def _operations(spec: dict[str, Any]):
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            yield path, method, operation


async def test_every_key_operation_declares_its_scope_and_error_responses() -> None:
    spec = await _spec()
    key_operations = [
        (path, method, op)
        for path, method, op in _operations(spec)
        if op.get("security") == [{"AgentBearer": []}, {"AgentHeader": []}]
    ]
    assert len(key_operations) >= 15
    for path, method, op in key_operations:
        assert op.get("x-required-scope"), f"{method} {path} has no scope"
        assert {"401", "403", "429"} <= set(op["responses"]), f"{method} {path}"
        assert "Retry-After" in op["responses"]["429"]["headers"]
    scopes = {op["x-required-scope"] for _, _, op in key_operations}
    assert scopes == {"ingest:write", "module:sync", "crm:write", "calls:read", "contacts:read"}


async def test_specific_routes_need_the_documented_scope() -> None:
    paths = (await _spec())["paths"]
    assert paths["/v1/integration/calls"]["get"]["x-required-scope"] == "calls:read"
    assert paths["/v1/integration/contacts/lookup"]["get"]["x-required-scope"] == "contacts:read"
    assert paths["/v1/crm/outcomes/bulk"]["post"]["x-required-scope"] == "crm:write"
    assert paths["/v1/ingest/calls"]["post"]["x-required-scope"] == "ingest:write"


async def test_public_and_user_routes_are_labelled_from_their_dependencies() -> None:
    paths = (await _spec())["paths"]
    assert paths["/v1/auth/login"]["post"]["security"] == []
    assert paths["/v1/webhooks"]["get"]["security"] == [{"CustomerJWT": []}]
    assert paths["/v1/auth/api-keys"]["post"]["security"] == [{"CustomerJWT": []}]


async def test_spec_documents_the_error_shape_and_describes_the_contract() -> None:
    spec = await _spec()
    error = spec["components"]["schemas"]["Error"]["properties"]["error"]
    assert set(error["properties"]) == {"code", "message", "retryable", "request_id"}
    description = spec["info"]["description"]
    for needle in ("Retry-After", "next_cursor", "calls:read", "no key scope", "Idempotency"):
        assert needle.lower() in description.lower(), needle
    assert "assistant" not in json.dumps(spec["paths"]).lower().replace("in-panel assistant", "")


async def test_rate_limit_error_carries_retry_after(monkeypatch) -> None:
    monkeypatch.setattr(ratelimit, "_get_redis", lambda: None)
    ratelimit._memory.clear()
    for _ in range(2):
        await ratelimit.enforce("contract-test", 2)
    with pytest.raises(ApiError) as limited:
        await ratelimit.enforce("contract-test", 2)
    assert limited.value.code == "rate_limited"
    assert 1 <= (limited.value.retry_after or 0) <= 60

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/limited")
    async def limited_route() -> None:
        raise limited.value

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        response = await client.get("/limited")
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) == limited.value.retry_after
    assert response.json()["error"]["retryable"] is True
