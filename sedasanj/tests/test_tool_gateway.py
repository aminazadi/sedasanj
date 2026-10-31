from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.config import get_settings
from app.errors import ApiError, install_error_handlers
from app.routers import internal_tools
from app.services import tool_gateway


@pytest.fixture(autouse=True)
def memory_backend(monkeypatch):
    monkeypatch.setattr(tool_gateway.ratelimit, "_get_redis", lambda: None)
    tool_gateway._seen_nonces.clear()
    tool_gateway._cached_results.clear()

    async def known_user(user_id):
        return SimpleNamespace(
            id=user_id,
            tenant_id=_USERS.get(user_id),
            role=_ROLES.get(user_id, "operator"),
            mobile_number=None,
            extension=None,
        )

    monkeypatch.setattr(tool_gateway, "_load_user", known_user)
    _USERS.clear()
    _ROLES.clear()


_USERS: dict = {}
_ROLES: dict = {}


def _request(role: str = "operator") -> tool_gateway.GatewayRequest:
    user_id, tenant_id = uuid4(), uuid4()
    _USERS[user_id] = tenant_id
    _ROLES[user_id] = role
    return tool_gateway.GatewayRequest(
        tool_call_id="tool-1",
        arguments={"dataset": "calls_analysis", "format": "csv", "limit": 10},
        principal=tool_gateway.GatewayPrincipal(id=user_id, tenant_id=tenant_id, role=role),
    )


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(internal_tools.router)
    return app


async def _post(name: str, body: bytes, headers: dict[str, str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        return await client.post(f"/v1/internal/tools/{name}", content=body, headers=headers)


async def test_signed_request_runs_tool_and_returns_result(monkeypatch):
    run = AsyncMock(return_value=({"count": 1}, 7))
    monkeypatch.setattr(tool_gateway, "execute_local", run)
    body = _request().model_dump_json().encode()
    response = await _post("get_current_time", body, tool_gateway.sign("get_current_time", body))
    assert response.status_code == 200
    assert response.json() == {"result": {"count": 1}, "duration_ms": 7}
    principal = run.await_args.args[2]
    assert principal.kind == "user" and principal.role == "operator"


async def test_tampered_body_and_wrong_tool_name_are_rejected(monkeypatch):
    run = AsyncMock(return_value=({}, 1))
    monkeypatch.setattr(tool_gateway, "execute_local", run)
    body = _request().model_dump_json().encode()
    headers = tool_gateway.sign("get_current_time", body)
    assert (await _post("get_current_time", body + b" ", headers)).status_code == 403
    assert (await _post("export_data", body, headers)).status_code == 403
    assert (await _post("get_current_time", body, {})).status_code == 403
    run.assert_not_awaited()


async def test_nonce_cannot_be_replayed(monkeypatch):
    monkeypatch.setattr(tool_gateway, "execute_local", AsyncMock(return_value=({}, 1)))
    body = _request().model_dump_json().encode()
    headers = tool_gateway.sign("get_current_time", body)
    assert (await _post("get_current_time", body, headers)).status_code == 200
    assert (await _post("get_current_time", body, headers)).status_code == 403


async def test_stale_timestamp_is_rejected(monkeypatch):
    real_time = time.time
    body = _request().model_dump_json().encode()
    with monkeypatch.context() as stale:
        stale.setattr(tool_gateway.time, "time", lambda: real_time() - 3600)
        headers = tool_gateway.sign("get_current_time", body)
    assert (await _post("get_current_time", body, headers)).status_code == 403


async def test_staff_or_unknown_roles_and_tools_are_refused():
    body = _request("agent").model_dump_json().encode()
    assert (
        await _post("get_current_time", body, tool_gateway.sign("get_current_time", body))
    ).status_code == 403
    body = _request().model_dump_json().encode()
    assert (
        await _post("drop_tables", body, tool_gateway.sign("drop_tables", body))
    ).status_code == 404


async def test_same_tool_call_id_is_idempotent(monkeypatch):
    run = AsyncMock(return_value=({"file": {"export_id": "x"}}, 3))
    monkeypatch.setattr(tool_gateway, "execute_local", run)
    request = _request()
    first = await tool_gateway.handle("export_data", request)
    second = await tool_gateway.handle("export_data", request)
    assert first == second
    assert run.await_count == 1


async def test_dispatch_runs_in_process_without_gateway_url(monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_gateway_url", None)
    run = AsyncMock(return_value=({"ok": True}, 2))
    monkeypatch.setattr(tool_gateway, "execute_local", run)
    principal = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), role="operator", mobile_number=None, extension=None
    )
    result = await tool_gateway.dispatch("get_current_time", "t1", {}, principal, None)
    assert result == ({"ok": True}, 2)


async def test_dispatch_posts_signed_webhook_and_maps_errors(monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_gateway_url", "http://api:8000")
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["signed"] = bool(request.headers.get("x-tool-signature"))
        body = json.loads(request.content)
        if body["tool_call_id"] == "bad":
            return httpx.Response(
                422, json={"error": {"code": "invalid_request", "message": "فیلتر را اصلاح کنید"}}
            )
        return httpx.Response(200, json={"result": {"count": 2}, "duration_ms": 5})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        tool_gateway.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    principal = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), role="org_admin", mobile_number=None, extension=None
    )
    assert await tool_gateway.dispatch("search_calls", "ok", {}, principal, None) == (
        {"count": 2},
        5,
    )
    assert seen == {"path": "/v1/internal/tools/search_calls", "signed": True}
    with pytest.raises(ApiError) as error:
        await tool_gateway.dispatch("search_calls", "bad", {}, principal, None)
    assert error.value.code == "invalid_request"


async def test_dispatch_falls_back_in_process_when_gateway_is_unreachable(monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_gateway_url", "http://api:8000")

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        tool_gateway.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    run = AsyncMock(return_value=({"local": True}, 1))
    monkeypatch.setattr(tool_gateway, "execute_local", run)
    principal = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), role="operator", mobile_number=None, extension=None
    )
    assert (await tool_gateway.dispatch("search_calls", "t", {}, principal, None))[0] == {
        "local": True
    }


async def test_signed_request_for_unknown_or_foreign_user_is_forbidden(monkeypatch):
    run = AsyncMock(return_value=({}, 1))
    monkeypatch.setattr(tool_gateway, "execute_local", run)
    body = _request().model_dump_json().encode()
    _USERS.clear()
    response = await _post("get_current_time", body, tool_gateway.sign("get_current_time", body))
    assert response.status_code == 403
    run.assert_not_awaited()
