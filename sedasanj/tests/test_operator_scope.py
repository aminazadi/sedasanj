from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.deps import Principal
from app.errors import ApiError
from app.models import Call
from app.schemas import UserCreate
from app.services import operator_scope as scope


def test_digits_only_strips_iranian_mobile_formatting() -> None:
    assert scope.digits_only("+98 912 123 4567") == "989121234567"
    assert scope.digits_only("0912-123-4567") == "09121234567"


def test_operator_does_not_gain_call_access_from_customer_mobile() -> None:
    call = Call(
        caller_number="+989121234567",
        dialed_number="02191000000",
        agent_extension="200",
    )
    assert not scope.call_visible_to_operator(call, mobile_number="09121234567", extension=None)


def test_operator_sees_call_when_extension_is_a_party() -> None:
    call = Call(caller_number="09120000000", dialed_number="101", agent_extension="101")
    assert scope.call_visible_to_operator(call, mobile_number=None, extension="101")


def test_short_extension_does_not_match_a_mobile_suffix() -> None:
    call = Call(caller_number="09121234101", dialed_number=None, agent_extension=None)
    assert not scope.call_visible_to_operator(call, mobile_number=None, extension="101")


def test_operator_without_numbers_sees_no_calls() -> None:
    call = Call(caller_number="09121234567", dialed_number="101", agent_extension="101")
    assert not scope.call_visible_to_operator(call, mobile_number=None, extension=None)


def test_org_admin_can_see_any_call() -> None:
    principal = Principal(kind="user", id=uuid4(), tenant_id=uuid4(), role="org_admin")
    call = Call(caller_number="09120000000", dialed_number="021", agent_extension="999")
    scope.assert_call_visible(call, principal)


def test_operator_cannot_open_a_foreign_call() -> None:
    principal = Principal(
        kind="user",
        id=uuid4(),
        tenant_id=uuid4(),
        role="operator",
        mobile_number="09121234567",
        extension="101",
    )
    call = Call(caller_number="09350000000", dialed_number="021", agent_extension="202")
    with pytest.raises(ApiError) as excinfo:
        scope.assert_call_visible(call, principal)
    assert excinfo.value.code == "not_found"


def test_identities_conflict_on_equivalent_mobiles() -> None:
    assert scope.identities_conflict("09121234567", None, "+989121234567", "101")
    assert not scope.identities_conflict("09121234567", "101", "09120000000", "202")


def test_operator_create_requires_a_number() -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            email="op@example.com",
            password="password1",
            role="operator",
        )
    payload = UserCreate(
        email="op@example.com",
        password="password1",
        role="operator",
        extension="101",
    )
    assert payload.extension == "101"
    assert payload.mobile_number is None


def test_require_operator_numbers_rejects_blank_operator() -> None:
    with pytest.raises(ApiError) as excinfo:
        scope.require_operator_numbers(role="operator", mobile_number=" ", extension=None)
    assert excinfo.value.code == "invalid_request"
