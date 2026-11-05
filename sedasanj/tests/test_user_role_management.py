from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app import deps
from app.deps import Principal
from app.errors import ApiError
from app.models import StaffUser, User
from app.routers import admin, auth
from app.schemas import StaffRoleUpdate, UserUpdate
from app.security import hash_password


def request():
    return Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})


@pytest.fixture
def staff_setup(monkeypatch):
    actor = StaffUser(id=uuid4(), role="super_admin", password_hash=hash_password("test-password"))
    target = StaffUser(id=uuid4(), role="support")
    principal = Principal("staff", actor.id, None, "super_admin")
    session = AsyncMock()
    session.get.side_effect = [actor, target]
    audit = AsyncMock()
    monkeypatch.setattr(admin.audit, "record", audit)
    return actor, target, principal, session, audit


@pytest.mark.parametrize("next_role", ["support", "super_admin"])
async def test_staff_role_change_revokes_refresh_and_audits(staff_setup, next_role):
    _, target, principal, session, audit = staff_setup
    target.role = "super_admin" if next_role == "support" else "support"
    previous = target.role
    result = await admin.update_staff_role(
        target.id,
        StaffRoleUpdate(role=next_role, current_password="test-password"),
        request(),
        principal,
        session,
    )
    assert result == {"id": str(target.id), "role": next_role}
    assert target.role == next_role
    session.flush.assert_awaited_once()
    statements = session.execute.await_args_list
    assert "pg_advisory_xact_lock" in str(statements[0].args[0])
    assert "staff_refresh_tokens" in str(statements[1].args[0])
    assert target.id in statements[1].args[0].compile().params.values()
    assert audit.await_args.kwargs["payload"] == {
        "staff_id": str(target.id),
        "previous_role": previous,
        "role": next_role,
    }


@pytest.mark.parametrize(
    "failure, expected",
    [
        ("password", "unauthorized"),
        ("totp", "unauthorized"),
        ("self", "invalid_request"),
        ("missing", "not_found"),
        ("demoted", "forbidden"),
        ("disabled", "forbidden"),
    ],
)
async def test_staff_role_change_rejects_unsafe_requests(
    staff_setup, monkeypatch, failure, expected
):
    actor, target, principal, session, audit = staff_setup
    password = "wrong-password" if failure == "password" else "test-password"
    if failure == "totp":
        actor.totp_secret = "test-secret"
        monkeypatch.setattr(admin, "verify_totp", lambda *_: False)
    if failure == "demoted":
        actor.role = "support"
    if failure == "disabled":
        actor.disabled_at = datetime.now(UTC)
    if failure == "missing":
        session.get.side_effect = [actor, None]
    with pytest.raises(ApiError) as caught:
        await admin.update_staff_role(
            actor.id if failure == "self" else target.id,
            StaffRoleUpdate(role="super_admin", current_password=password),
            request(),
            principal,
            session,
        )
    assert caught.value.code == expected
    session.flush.assert_not_awaited()
    audit.assert_not_awaited()
    assert target.role == "support"


@pytest.mark.parametrize("role", ["org_admin", "operator", "", None])
def test_staff_role_schema_rejects_invalid_roles(role):
    with pytest.raises(ValidationError):
        StaffRoleUpdate(role=role, current_password="test-password")


async def test_demoted_staff_cannot_keep_token_role(monkeypatch):
    staff_id = uuid4()
    session = AsyncMock()
    session.get.return_value = StaffUser(id=staff_id, role="support")

    @asynccontextmanager
    async def scope(*args, **kwargs):
        yield session

    monkeypatch.setattr(deps, "session_scope", scope)
    monkeypatch.setattr(
        deps,
        "decode_access_token",
        lambda _: {
            "actor": "staff",
            "sub": str(staff_id),
            "role": "super_admin",
        },
    )
    principal = await deps.current_staff(request(), "Bearer old-access-token")
    assert principal.role == "support"
    with pytest.raises(ApiError) as caught:
        deps.require_staff_roles("super_admin")(principal)
    assert caught.value.code == "forbidden"


@pytest.fixture
def member_setup(monkeypatch):
    principal = Principal("user", uuid4(), uuid4(), "org_admin")
    member = User(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        email="member@example.com",
        role="viewer",
        extension="201",
        created_at=datetime.now(UTC),
    )
    session = AsyncMock()
    session.get.return_value = member
    quota, unique, projection, audit, lock = (AsyncMock() for _ in range(5))
    monkeypatch.setattr(auth.operator_scope, "assert_operator_quota", quota)
    monkeypatch.setattr(auth.operator_scope, "assert_unique_operator_numbers", unique)
    monkeypatch.setattr(auth.identity_projection, "stage_user_projection", projection)
    monkeypatch.setattr(auth.audit, "record", audit)
    monkeypatch.setattr(auth.extensions, "lock_inventory", lock)
    monkeypatch.setattr(
        auth, "get_settings", lambda: SimpleNamespace(tenant_databases_enabled=False)
    )
    return principal, member, session, quota, unique, projection, audit


@pytest.mark.parametrize(
    "old_role, new_role",
    [
        ("viewer", "org_admin"),
        ("org_admin", "viewer"),
        ("viewer", "operator"),
        ("operator", "viewer"),
        ("org_admin", "operator"),
        ("operator", "org_admin"),
    ],
)
async def test_member_role_changes_reconcile_identity_and_quota(member_setup, old_role, new_role):
    principal, member, session, quota, unique, projection, audit = member_setup
    member.role = old_role
    result = await auth.update_user(
        member.id, UserUpdate(role=new_role), request(), session, principal
    )
    assert result.role == new_role
    assert quota.await_count == int(new_role == "operator")
    unique.assert_awaited_once()
    projection.assert_awaited_once_with(session, member, reconcile_extension=True)
    assert audit.await_args.kwargs["payload"]["role"] == new_role


@pytest.mark.parametrize(
    "failure, code",
    [
        ("foreign", "not_found"),
        ("self", "invalid_request"),
        ("null", "invalid_request"),
        ("numbers", "invalid_request"),
        ("quota", "quota_exceeded"),
        ("duplicate", "conflict_idempotency"),
    ],
)
async def test_member_role_change_preserves_validation(member_setup, failure, code):
    principal, member, session, quota, unique, projection, audit = member_setup
    payload = UserUpdate(role="operator")
    if failure == "foreign":
        member.tenant_id = uuid4()
    elif failure == "self":
        member.id = principal.id
    elif failure == "null":
        payload = UserUpdate(role=None)
    elif failure == "numbers":
        member.extension = None
    elif failure == "quota":
        quota.side_effect = ApiError("quota_exceeded", "operator quota reached")
    elif failure == "duplicate":
        unique.side_effect = ApiError("conflict_idempotency", "number already assigned")
    with pytest.raises(ApiError) as caught:
        await auth.update_user(member.id, payload, request(), session, principal)
    assert caught.value.code == code
    assert member.role == "viewer"
    projection.assert_not_awaited()
    audit.assert_not_awaited()
