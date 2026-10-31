from __future__ import annotations

import json

from plan_routes import api_routes, dependency_calls

from app import deps
from app.main import create_app
from app.services import assistant_socket


async def test_customer_openapi_never_lists_assistant_routes() -> None:
    app = create_app()
    route = next(r for r in app.routes if getattr(r, "path", None) == "/v1/openapi/customer.json")
    paths = json.loads((await route.endpoint()).body)["paths"]
    forbidden = ("/v1/assistant", "/v1/internal", "/v1/admin", "operator-score", "operator-coach")
    assert not [p for p in paths if any(marker in p for marker in forbidden)]


def test_default_framework_docs_are_disabled() -> None:
    paths = {getattr(route, "path", None) for route in create_app().routes}
    assert not paths & {"/docs", "/redoc", "/openapi.json"}


def test_route_inspection_sees_the_assistant_routes() -> None:
    # Guards the guards: an empty route list would make the checks below pass vacuously.
    paths = {route.path for route in api_routes()}
    assert "/v1/assistant/conversations" in paths
    assert "/v1/ingest/calls" in paths


def test_api_key_dependency_never_guards_assistant_routes() -> None:
    offenders = [
        route.path
        for route in api_routes()
        if "assistant" in route.path or "operator-score" in route.path
        if deps.current_api_key in dependency_calls(route.dependant)
    ]
    assert offenders == []


def test_assistant_routes_require_a_tenant_user() -> None:
    assistant = [r for r in api_routes() if r.path.startswith("/v1/assistant")]
    assert assistant
    for route in assistant:
        assert deps.current_user in dependency_calls(route.dependant), route.path


def test_socket_origin_check_is_not_disabled() -> None:
    # An empty list makes python-engineio skip origin validation entirely.
    assert assistant_socket.sio.eio.cors_allowed_origins != []
