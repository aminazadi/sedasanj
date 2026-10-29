from __future__ import annotations

import ast
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.deps import client_ip
from app.errors import ERROR_STATUS, ApiError
from app.services import ingest

APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "api" / "app"


def test_every_literal_api_error_code_is_registered() -> None:
    unknown: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ApiError"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value not in ERROR_STATUS
            ):
                unknown.append(f"{path.name}:{node.lineno} {node.args[0].value}")
    assert unknown == []


def _request(headers: dict[str, str], host: str | None) -> Any:
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host) if host else None)


def test_client_ip_ignores_spoofable_forwarded_header() -> None:
    request = _request({"x-forwarded-for": "6.6.6.6"}, "10.0.0.5")
    assert client_ip(request) == "10.0.0.5"
    assert client_ip(_request({}, None)) is None


class _Result:
    def __init__(self, call: Any) -> None:
        self._call = call

    def scalar_one_or_none(self) -> Any:
        return self._call


class _Session:
    def __init__(self, call: Any) -> None:
        self._call = call
        self.updates = 0

    async def execute(self, statement: Any) -> _Result:
        if str(statement).lstrip().upper().startswith("UPDATE"):
            self.updates += 1
        return _Result(self._call)


def _patch_session(monkeypatch: pytest.MonkeyPatch, session: _Session) -> None:
    @asynccontextmanager
    async def scope(_tenant_id: Any) -> Any:
        yield session

    monkeypatch.setattr(ingest, "session_scope", scope)


async def test_replay_does_not_accept_failed_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    call = SimpleNamespace(id=uuid4(), status="failed_terminal", audio_id=None)
    session = _Session(call)
    _patch_session(monkeypatch, session)
    assert await ingest._replay(uuid4(), "1700000000.1") is None
    assert session.updates == 1


async def test_replay_keeps_post_storage_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    call = SimpleNamespace(id=uuid4(), status="failed_terminal", audio_id=uuid4())
    session = _Session(call)
    _patch_session(monkeypatch, session)

    async def no_reservation(_session: Any, _call_id: Any) -> None:
        return None

    monkeypatch.setattr(ingest, "_reservation_id", no_reservation)
    replay = await ingest._replay(uuid4(), "1700000000.1")
    assert replay is not None and replay.status == "failed_terminal"
    assert session.updates == 0


def test_new_error_codes_map_to_statuses() -> None:
    assert ApiError("conflict", "x").status_code == 409
    assert ApiError("worker_timeout", "x").status_code == 504


class _SecretBody(BaseModel):
    password: str
    age: int


def test_validation_errors_do_not_echo_submitted_values() -> None:
    import httpx
    from fastapi import FastAPI
    from app.errors import install_error_handlers

    app = FastAPI()
    install_error_handlers(app)

    @app.post("/x")
    async def x(body: _SecretBody) -> dict[str, bool]:  # pragma: no cover - never reached
        return {"ok": True}

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.post(
                "/x", json={"password": "hunter2-secret", "age": "not-a-number"}
            )

    import asyncio

    response = asyncio.run(call())
    assert response.status_code == 422
    assert "hunter2-secret" not in response.text and "not-a-number" not in response.text
    assert "age" in response.json()["error"]["message"]


def test_client_errors_are_not_retryable_but_server_errors_are() -> None:
    import asyncio

    import httpx
    from fastapi import FastAPI

    from app.errors import install_error_handlers

    app = FastAPI()
    install_error_handlers(app)

    async def call(method: str, path: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.request(method, path)

    missing = asyncio.run(call("GET", "/nope"))
    assert missing.status_code == 404 and missing.json()["error"]["retryable"] is False

    @app.get("/only-get")
    async def only_get() -> dict[str, bool]:
        return {"ok": True}

    wrong_method = asyncio.run(call("POST", "/only-get"))
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["retryable"] is False
    assert wrong_method.json()["error"]["code"] == "invalid_request"
