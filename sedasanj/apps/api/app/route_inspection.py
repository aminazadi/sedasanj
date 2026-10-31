"""Read the route table with the dependencies each route really has.

FastAPI 0.141 wraps included routers in `_IncludedRouter`, so `app.routes` exposes neither
`path` nor `dependant`. The router modules' own `router.routes` do, and that is what the
published OpenAPI security and the isolation tests are built from.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from fastapi.routing import APIRoute

from app import deps, routers


def api_routes() -> list[APIRoute]:
    found: list[APIRoute] = []
    for info in pkgutil.iter_modules(routers.__path__):
        module = importlib.import_module(f"app.routers.{info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            found.extend(route for route in router.routes if isinstance(route, APIRoute))
    return found


def dependency_calls(dependant: Any) -> set[Any]:
    calls = {dependant.call}
    for sub in dependant.dependencies:
        calls |= dependency_calls(sub)
    return calls


def scope_names(route: APIRoute) -> set[str]:
    """Scope strings captured by `require_scope` closures on this route."""
    names: set[str] = set()
    for call in dependency_calls(route.dependant):
        for cell in getattr(call, "__closure__", None) or ():
            value = cell.cell_contents
            if isinstance(value, str) and ":" in value and " " not in value:
                names.add(value)
    return names


def auth_kind(route: APIRoute) -> str:
    """`api_key`, `user` or `public`, from the dependencies the route declares."""
    calls = dependency_calls(route.dependant)
    if deps.current_api_key in calls:
        return "api_key"
    if deps.current_user in calls:
        return "user"
    return "public"
