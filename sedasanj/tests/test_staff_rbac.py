"""Staff RBAC: platform-shaping admin routes must be super_admin only (WSTG-ATHZ-03)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute

from app.deps import Principal, require_staff_roles
from app.errors import ApiError
from app.main import create_app

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Mutating staff routes that `support` may legitimately call (day-to-day tenant
# operations and a staff member managing their own login). Everything else that
# mutates under an admin prefix must require the super_admin role.
SUPPORT_ALLOWED: set[tuple[str, str]] = {
    ("POST", "/v1/admin/auth/check"),
    ("POST", "/v1/admin/auth/login"),
    ("POST", "/v1/admin/auth/refresh"),
    ("POST", "/v1/admin/auth/logout"),
    ("POST", "/v1/admin/auth/totp/setup"),
    ("POST", "/v1/admin/auth/totp/enable"),
    ("POST", "/v1/admin/auth/totp/disable"),
    ("POST", "/v1/admin/jobs/{job_id}/requeue"),
    ("POST", "/v1/admin/settings/test-correction"),
    ("PUT", "/v1/admin/tenants/{tenant_id}/ai-instructions"),
    ("PATCH", "/v1/admin/commerce/leads/{lead_id}"),
    ("POST", "/v1/admin/commerce/subscriptions/{subscription_id}/actions"),
    ("POST", "/v1/admin/commerce/orders/{order_id}/cancel"),
    ("POST", "/v1/admin/commerce/payments/{payment_id}/reconcile"),
    ("PATCH", "/v1/admin/commerce/installations/{installation_id}"),
}


def _dependency_names(dependant: Any) -> set[str]:
    names: set[str] = set()
    stack = [dependant]
    while stack:
        node = stack.pop()
        if node.call is not None:
            names.add(getattr(node.call, "__qualname__", ""))
        stack.extend(node.dependencies)
    return names


def _admin_mutating_routes() -> list[tuple[str, str, Any]]:
    """Return (method, full path, dependant) for every mutating route under an /admin/ prefix.

    FastAPI wraps included routers in `_IncludedRouter`; its effective route contexts carry
    the full path and the merged dependency tree.
    """
    app = create_app()
    found: list[tuple[str, str, Any]] = []
    for route in app.routes:
        contexts: list[Any]
        if isinstance(route, APIRoute):
            contexts = [route]
        else:
            contexts = list(route.effective_route_contexts())
        for ctx in contexts:
            if "/admin/" not in ctx.path + "/":
                continue
            for method in sorted(set(ctx.methods) & MUTATING):
                found.append((method, ctx.path, ctx.dependant))
    return found


def test_admin_route_scan_finds_routes() -> None:
    assert len(_admin_mutating_routes()) > 20


def test_every_mutating_admin_route_requires_super_admin_or_is_allowlisted() -> None:
    offenders: list[str] = []
    for method, path, dependant in _admin_mutating_routes():
        if (method, path) in SUPPORT_ALLOWED:
            continue
        names = _dependency_names(dependant)
        if not any("require_staff_roles" in name for name in names):
            offenders.append(f"{method} {path}")
    assert offenders == [], "mutating admin routes without a staff-role check"


def test_support_allowlist_has_no_stale_entries() -> None:
    existing = {(method, path) for method, path, _ in _admin_mutating_routes()}
    assert existing >= SUPPORT_ALLOWED


def _staff(role: str) -> Principal:
    return Principal(kind="staff", id=uuid4(), tenant_id=None, role=role)


@pytest.mark.parametrize("role", ["support", "", "org_admin"])
def test_super_admin_dependency_rejects_other_roles(role: str) -> None:
    dependency: Any = require_staff_roles("super_admin")
    with pytest.raises(ApiError) as caught:
        dependency(_staff(role))
    assert caught.value.code == "forbidden"


def test_super_admin_dependency_accepts_super_admin() -> None:
    dependency: Any = require_staff_roles("super_admin")
    principal = _staff("super_admin")
    assert dependency(principal) is principal
