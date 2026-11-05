from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.requests import Request

from app import deps
from app.deps import Principal
from app.errors import ERROR_STATUS, ApiError
from app.main import create_app
from app.models import User
from app.routers import auth
from app.schemas import UserCreate, UserOut, UserUpdate
from app.security import create_access_token, decode_access_token
from app.services import panel_access as access
from app.services.identity_projection import _user_payload


def request(path="/v1/calls", method="GET"):
    return Request(
        {
            "type": "http",
            "path": path,
            "method": method,
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "server": ("test", 80),
            "query_string": b"",
        }
    )


def test_every_panel_route_is_classified():
    missed = []
    for route in create_app().routes:
        contexts = (
            [route] if isinstance(route, APIRoute) else list(route.effective_route_contexts())
        )
        for ctx in contexts:
            names = set()
            stack = [ctx.dependant]
            while stack:
                node = stack.pop()
                names.add(getattr(node.call, "__name__", ""))
                stack.extend(node.dependencies)
            if not names.intersection({"current_user", "current_meeting_actor"}):
                continue
            for method in ctx.methods:
                if access.request_sections(ctx.path, method) is None:
                    missed.append((method, ctx.path))
    assert missed == []


@pytest.mark.parametrize("section", list(access.SECTION_LABELS))
def test_each_section_is_independently_assignable(section):
    assert access.effective_sections("org_admin", [section]) == [section]
    assert access.effective_sections("org_admin", []) == []
    assert access.effective_sections("org_admin", None) == list(access.SECTION_LABELS)


def test_role_scope_remains_a_ceiling():
    assert "users" not in access.effective_sections("operator", ["users", "calls"])
    assert "calls" in access.effective_sections("operator", ["users", "calls"])
    assert "reports" not in access.effective_sections("viewer", ["reports"])


@pytest.mark.parametrize("payload", [[], ["calls"], None])
def test_access_schema_and_projection_preserve_none_and_empty(payload):
    user = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="a@example.com",
        role="org_admin",
        created_at=datetime.now(UTC),
        panel_permissions=payload,
    )
    assert UserOut.model_validate(user).panel_permissions == payload
    assert _user_payload(user)["panel_permissions"] == payload
    token = create_access_token(
        subject=user.id, tenant_id=user.tenant_id, role=user.role, panel_permissions=payload
    )
    assert decode_access_token(token)["panel_permissions"] == access.effective_sections(
        user.role, payload
    )


@pytest.mark.parametrize("value", [["admin"], "calls", ["calls"] * 21])
def test_unknown_or_malformed_permissions_are_rejected(value):
    with pytest.raises(ValidationError):
        UserUpdate(panel_permissions=value)


@pytest.mark.parametrize(
    "path, method",
    [
        ("/v1/calls", "GET"),
        ("/v1/calls/a/audio/content", "GET"),
        ("/v1/calls/a", "DELETE"),
        ("/v1/meetings", "GET"),
        ("/v1/assistant/conversations", "POST"),
        ("/v1/auth/users", "POST"),
        ("/v1/account/data/backup", "POST"),
        ("/v1/unknown/new-feature", "GET"),
    ],
)
def test_empty_grants_cannot_bypass_api_by_direct_url(path, method):
    principal = Principal("user", uuid4(), uuid4(), "org_admin", panel_permissions=frozenset())
    with pytest.raises(ApiError) as caught:
        access.assert_request_access(principal, path, method)
    assert caught.value.code == "panel_access_denied"
    assert ERROR_STATUS[caught.value.code] == 403


@pytest.mark.parametrize(
    "path", ["/v1/auth/me", "/v1/auth/totp", "/v1/account", "/v1/auth/panel-access-options"]
)
def test_profile_and_access_metadata_survive_empty_grants(path):
    principal = Principal("user", uuid4(), uuid4(), "org_admin", panel_permissions=frozenset())
    access.assert_request_access(principal, path, "GET")


async def test_stale_token_cannot_restore_revoked_section(monkeypatch):
    user = User(id=uuid4(), tenant_id=uuid4(), role="org_admin", panel_permissions=["contacts"])
    session = AsyncMock()
    session.get.return_value = user

    @asynccontextmanager
    async def scope(*args, **kwargs):
        yield session

    monkeypatch.setattr(deps, "session_scope", scope)
    monkeypatch.setattr(
        deps,
        "decode_access_token",
        lambda _: {
            "actor": "user",
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "panel_permissions": ["calls"],
        },
    )
    monkeypatch.setattr(deps, "_assert_tenant_active", AsyncMock())
    monkeypatch.setattr(deps.ratelimit, "enforce", AsyncMock())
    with pytest.raises(ApiError) as caught:
        await deps.current_user(request(), "Bearer old-token")
    assert caught.value.code == "panel_access_denied"
    principal = await deps.current_user(request("/v1/contacts"), "Bearer old-token")
    assert principal.panel_permissions == frozenset({"contacts"})


@pytest.mark.parametrize("selected", [["calls", "users"], None])
def test_restricted_admin_cannot_delegate_more_access(selected):
    principal = Principal(
        "user", uuid4(), uuid4(), "org_admin", panel_permissions=frozenset({"users"})
    )
    with pytest.raises(ApiError) as caught:
        access.assert_can_delegate(principal, "org_admin", selected)
    assert caught.value.code == "panel_access_denied"
    access.assert_can_delegate(principal, "org_admin", ["users"])


@pytest.mark.parametrize(
    "change",
    [
        {"role": "viewer"},
        {"role": "operator"},
        {"panel_permissions": []},
        {"panel_permissions": ["calls"]},
    ],
)
async def test_primary_admin_access_cannot_be_changed(monkeypatch, change):
    tenant = uuid4()
    actor = Principal("user", uuid4(), tenant, "org_admin")
    owner = User(
        id=uuid4(),
        tenant_id=tenant,
        email="owner@example.com",
        role="org_admin",
        is_primary_admin=True,
        panel_permissions=None,
    )
    session = AsyncMock()
    session.get.return_value = owner
    projection = AsyncMock()
    monkeypatch.setattr(auth.identity_projection, "stage_user_projection", projection)
    with pytest.raises(ApiError) as caught:
        await auth.update_user(
            owner.id, UserUpdate(**change), request(method="PATCH"), session, actor
        )
    assert caught.value.code == "primary_admin_protected"
    assert owner.role == "org_admin" and owner.panel_permissions is None
    session.flush.assert_not_awaited()
    projection.assert_not_awaited()


async def test_primary_admin_cannot_be_deleted_by_another_admin(monkeypatch):
    tenant = uuid4()
    actor = Principal("user", uuid4(), tenant, "org_admin")
    owner = User(id=uuid4(), tenant_id=tenant, role="org_admin", is_primary_admin=True)
    session = AsyncMock()
    session.get.return_value = owner
    with pytest.raises(ApiError) as caught:
        await auth.delete_user(owner.id, request(method="DELETE"), session, actor)
    assert caught.value.code == "primary_admin_protected"
    session.delete.assert_not_awaited()


def test_primary_marker_cannot_be_assigned_through_member_payload():
    payload = UserCreate(
        email="test@example.com", password="password1", role="viewer", is_primary_admin=True
    )
    assert "is_primary_admin" not in payload.model_dump()


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/v1/calls"),
        ("GET", "/v1/meetings"),
        ("GET", "/v1/auth/users"),
        ("POST", "/v1/assistant/conversations"),
    ],
)
async def test_http_denial_uses_stable_403_code(monkeypatch, method, path):
    import httpx

    user = User(id=uuid4(), tenant_id=uuid4(), role="org_admin", panel_permissions=[])
    session = AsyncMock()
    session.get.return_value = user

    @asynccontextmanager
    async def scope(*args, **kwargs):
        yield session

    monkeypatch.setattr(deps, "session_scope", scope)
    monkeypatch.setattr(
        deps,
        "decode_access_token",
        lambda _: {"actor": "user", "sub": str(user.id), "tenant_id": str(user.tenant_id)},
    )
    monkeypatch.setattr(deps, "_assert_tenant_active", AsyncMock())
    monkeypatch.setattr(deps.ratelimit, "enforce", AsyncMock())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.request(method, path, headers={"Authorization": "Bearer old-token"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "panel_access_denied"


@pytest.mark.parametrize("selected,allowed", [([], False), (["meetings"], True)])
async def test_mobile_tokens_observe_current_owner_permissions(monkeypatch, selected, allowed):
    from unittest.mock import MagicMock

    from app.models import ApiKey

    owner = User(id=uuid4(), tenant_id=uuid4(), role="operator", panel_permissions=selected)
    key = ApiKey(
        id=uuid4(),
        tenant_id=owner.tenant_id,
        user_id=owner.id,
        kind="mobile",
        scopes=["meetings:write"],
        allowed_cidrs=[],
        last_used_at=datetime.now(UTC),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = key
    session = AsyncMock()
    session.execute.return_value = result
    session.get.return_value = owner

    @asynccontextmanager
    async def scope(*args, **kwargs):
        yield session

    monkeypatch.setattr(deps, "session_scope", scope)
    monkeypatch.setattr(deps, "_assert_tenant_active", AsyncMock())
    if allowed:
        principal = await deps.current_api_key(
            request("/v1/meetings/sessions", "POST"), "Bearer test-mobile-key"
        )
        assert principal.panel_permissions == frozenset({"meetings"})
    else:
        with pytest.raises(ApiError) as caught:
            await deps.current_api_key(
                request("/v1/meetings/sessions", "POST"), "Bearer test-mobile-key"
            )
        assert caught.value.code == "panel_access_denied"


@pytest.mark.asyncio
async def test_primary_admin_profile_and_password_reset_blocked_for_others(monkeypatch):
    tenant = uuid4()
    actor = Principal("user", uuid4(), tenant, "org_admin")
    owner = User(id=uuid4(), tenant_id=tenant, role="org_admin", is_primary_admin=True)
    session = AsyncMock()
    session.get.return_value = owner
    monkeypatch.setattr(auth.ratelimit, "enforce", AsyncMock())
    with pytest.raises(ApiError) as caught:
        await auth.update_user(
            owner.id, UserUpdate(display_name="x"), request(method="PATCH"), session, actor
        )
    assert caught.value.code == "primary_admin_protected"
    with pytest.raises(ApiError) as caught:
        await auth.request_member_password_reset(owner.id, request(), session, actor)
    assert caught.value.code == "primary_admin_protected"
