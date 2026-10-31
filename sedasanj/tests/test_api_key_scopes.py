from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app import deps
from app.errors import ApiError
from app.schemas import ApiKeyCreate, ApiKeyUpdate
from app.services.api_scopes import API_KEY_SCOPES, ip_allowed, normalize_cidrs


def test_no_assistant_scope_exists() -> None:
    assert not [scope for scope in API_KEY_SCOPES if "assistant" in scope]


def test_new_keys_default_to_least_privilege() -> None:
    created = ApiKeyCreate()
    assert created.scopes == ["ingest:write", "module:sync"]
    assert "crm:write" not in created.scopes


def test_unknown_or_assistant_scope_is_rejected() -> None:
    for scope in ("assistant:read", "calls:write", "*"):
        with pytest.raises(ValidationError):
            ApiKeyCreate(scopes=[scope])
    with pytest.raises(ValidationError):
        ApiKeyCreate(scopes=[])


def test_expiry_must_be_future_and_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        ApiKeyCreate(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    with pytest.raises(ValidationError):
        ApiKeyCreate(expires_at=datetime.now() + timedelta(days=1))  # noqa: DTZ005
    assert ApiKeyCreate(expires_at=datetime.now(UTC) + timedelta(days=1)).expires_at is not None
    cleared = ApiKeyUpdate.model_validate({"expires_at": None})
    assert "expires_at" in cleared.model_fields_set and cleared.expires_at is None


def test_cidr_validation_and_matching() -> None:
    assert normalize_cidrs(["10.0.0.5", "10.0.0.0/24 ", "10.0.0.5/32"]) == [
        "10.0.0.5/32",
        "10.0.0.0/24",
    ]
    with pytest.raises(ValidationError):
        ApiKeyCreate(allowed_cidrs=["not-an-ip"])
    assert ip_allowed([], "203.0.113.9")
    assert ip_allowed(["203.0.113.0/24"], "203.0.113.9")
    assert not ip_allowed(["203.0.113.0/24"], "198.51.100.1")
    assert not ip_allowed(["203.0.113.0/24"], None)
    assert ip_allowed(["2001:db8::/32"], "2001:db8::1")


async def test_require_scope_allows_a_granted_scope_and_audits_a_denial(monkeypatch) -> None:
    record = AsyncMock()

    @asynccontextmanager
    async def fake_session(*args, **kwargs):
        yield object()

    monkeypatch.setattr(deps, "session_scope", fake_session)
    monkeypatch.setattr(deps.audit, "record", record)
    limiter = AsyncMock()
    monkeypatch.setattr(deps.ratelimit, "enforce", limiter)
    request = SimpleNamespace(url=SimpleNamespace(path="/v1/crm/outcomes"), client=None)
    key = deps.Principal(
        kind="api_key",
        id=uuid4(),
        tenant_id=uuid4(),
        role="agent",
        scopes=frozenset({"ingest:write"}),
    )

    assert await deps.require_scope("ingest:write")(request, key) is key
    assert limiter.await_args.args[0] == f"key:{key.id}"
    record.assert_not_awaited()

    reader = deps.Principal(
        kind="api_key",
        id=uuid4(),
        tenant_id=uuid4(),
        role="agent",
        scopes=frozenset({"calls:read"}),
    )
    await deps.require_scope("calls:read")(request, reader)
    assert limiter.await_args.args[0] == f"key-read:{reader.id}"

    with pytest.raises(ApiError) as denied:
        await deps.require_scope("crm:write")(request, key)
    assert denied.value.code == "api_key_scope_denied"
    assert denied.value.status_code == 403
    assert record.await_args.kwargs["action"] == "api_key.denied.api_key_scope_denied"


def test_new_error_codes_have_help_pages() -> None:
    import importlib.util
    from pathlib import Path

    from app.errors import ERROR_STATUS

    path = Path(__file__).parents[1] / "apps/api/alembic/versions/0081_api_key_help_content.py"
    spec = importlib.util.spec_from_file_location("api_key_help_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    codes = {code for code, *_ in module.ERRORS}
    assert codes == {"api_key_scope_denied", "api_key_expired", "ip_not_allowed"}
    assert codes <= set(ERROR_STATUS)
