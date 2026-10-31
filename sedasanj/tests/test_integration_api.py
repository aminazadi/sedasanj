from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from plan_routes import api_routes, dependency_calls, scope_names
from pydantic import ValidationError

from app import deps
from app.errors import ApiError
from app.routers import kpi
from app.services import ingest


def _routes(prefix: str) -> list[Any]:
    return [r for r in api_routes() if r.path.startswith(prefix)]


def test_integration_routes_need_a_key_scope_and_never_a_user_token() -> None:
    routes = _routes("/v1/integration")
    assert len(routes) == 4
    for route in routes:
        calls = dependency_calls(route.dependant)
        assert deps.current_api_key in calls, route.path
        assert deps.current_user not in calls, route.path
        assert scope_names(route) & {"calls:read", "contacts:read"}, route.path


def test_crm_routes_need_crm_scope() -> None:
    routes = _routes("/v1/crm")
    assert {(r.path, tuple(sorted(r.methods))) for r in routes} == {
        ("/v1/crm/outcomes", ("GET",)),
        ("/v1/crm/outcomes", ("POST",)),
        ("/v1/crm/outcomes/bulk", ("POST",)),
    }
    for route in routes:
        assert "crm:write" in scope_names(route), route.path


def test_every_api_key_route_declares_a_scope() -> None:
    unscoped = [
        f"{route.path}"
        for route in api_routes()
        if deps.current_api_key in dependency_calls(route.dependant) and not scope_names(route)
    ]
    assert unscoped == []


def _outcome(**extra: Any) -> dict[str, Any]:
    return {
        "external_lead_id": "L-1",
        "outcome": "won",
        "occurred_at": datetime.now(UTC).isoformat(),
        **extra,
    }


def test_crm_metadata_is_bounded() -> None:
    assert kpi.CrmOutcomeIn(**_outcome(metadata={"deal": "A", "n": 3})).metadata == {
        "deal": "A",
        "n": 3,
    }
    with pytest.raises(ValidationError):
        kpi.CrmOutcomeIn(**_outcome(metadata={f"k{i}": "x" for i in range(21)}))
    with pytest.raises(ValidationError):
        kpi.CrmOutcomeIn(**_outcome(metadata={"big": "x" * 5000}))
    with pytest.raises(ValidationError):
        kpi.CrmOutcomeIn(**_outcome(metadata={"nested": {"a": 1}}))


def test_crm_bulk_is_capped() -> None:
    with pytest.raises(ValidationError):
        kpi.CrmOutcomeBulkIn(items=[])
    with pytest.raises(ValidationError):
        kpi.CrmOutcomeBulkIn(items=[kpi.CrmOutcomeIn(**_outcome())] * (kpi.MAX_CRM_BULK_ITEMS + 1))


async def test_strict_match_rejects_an_unknown_call_reference() -> None:
    class Result:
        def scalar_one_or_none(self) -> None:
            return None

    session = SimpleNamespace(execute=AsyncMock(return_value=Result()))
    payload = kpi.CrmOutcomeIn(**_outcome(external_call_reference="nope", strict_match=True))
    with pytest.raises(ApiError) as error:
        await kpi._upsert_outcome(session, uuid4(), payload)
    assert error.value.code == "not_found"

    bare = kpi.CrmOutcomeIn(**_outcome(strict_match=True))
    with pytest.raises(ApiError) as error:
        await kpi._upsert_outcome(session, uuid4(), bare)
    assert error.value.code == "invalid_request"


async def test_replay_with_different_numbers_is_an_idempotency_conflict(monkeypatch) -> None:
    existing = SimpleNamespace(
        id=uuid4(),
        status="complete",
        audio_id=uuid4(),
        caller_number="09120000000",
        dialed_number="1000",
    )

    class Result:
        def scalar_one_or_none(self) -> Any:
            return existing

    @asynccontextmanager
    async def fake_scope(*args: Any, **kwargs: Any):
        yield SimpleNamespace(execute=AsyncMock(return_value=Result()))

    monkeypatch.setattr(ingest, "session_scope", fake_scope)
    monkeypatch.setattr(ingest, "_reservation_id", AsyncMock(return_value=None))

    same = await ingest._replay(uuid4(), "1.1", parties=("09120000000", "1000"))
    assert same is not None and same.call_id == existing.id
    no_binding = await ingest._replay(uuid4(), "1.1")
    assert no_binding is not None

    with pytest.raises(ApiError) as conflict:
        await ingest._replay(uuid4(), "1.1", parties=("09130000000", "1000"))
    assert conflict.value.code == "conflict_idempotency"
    assert conflict.value.status_code == 409


async def test_customer_openapi_documents_integration_routes_with_key_security() -> None:
    import json

    from app.main import create_app

    app = create_app()
    route = next(r for r in app.routes if getattr(r, "path", None) == "/v1/openapi/customer.json")
    paths = json.loads((await route.endpoint()).body)["paths"]
    assert "/v1/integration/calls" in paths
    assert "/v1/integration/contacts/lookup" in paths
    assert "/v1/crm/outcomes/bulk" in paths
    security = paths["/v1/integration/calls"]["get"]["security"]
    assert security == [{"AgentBearer": []}, {"AgentHeader": []}]
