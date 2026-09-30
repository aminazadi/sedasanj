"""Scope tenant calls to the operator who was a party on the call."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.errors import ApiError
from app.models import Call, CallOperatorAssignment, User
from app.services import entitlements

if TYPE_CHECKING:
    from app.deps import Principal

_NON_DIGITS = re.compile(r"\D+")
_MOBILE_MIN_DIGITS = 10


def digits_only(value: str | None) -> str:
    if not value:
        return ""
    return _NON_DIGITS.sub("", value)


def identities_of(*, mobile_number: str | None, extension: str | None) -> list[str]:
    seen: list[str] = []
    for raw in (mobile_number, extension):
        ident = digits_only(raw)
        if ident and ident not in seen:
            seen.append(ident)
    return seen


def number_matches(value: str | None, identities: Sequence[str]) -> bool:
    digits = digits_only(value)
    if not digits or not identities:
        return False
    for ident in identities:
        if digits == ident:
            return True
        if (
            len(ident) >= _MOBILE_MIN_DIGITS
            and len(digits) >= _MOBILE_MIN_DIGITS
            and digits[-_MOBILE_MIN_DIGITS:] == ident[-_MOBILE_MIN_DIGITS:]
        ):
            return True
    return False


def call_visible_to_operator(
    call: Call, *, mobile_number: str | None, extension: str | None
) -> bool:
    del mobile_number
    operator_extension = digits_only(extension)
    return bool(
        operator_extension
        and digits_only(call.agent_extension) == operator_extension
    )


def is_operator(principal: Principal) -> bool:
    return principal.kind == "user" and principal.role == "operator"


def operator_identities(principal: Principal) -> list[str]:
    return identities_of(mobile_number=principal.mobile_number, extension=principal.extension)


def _digit_expr(column: Any) -> Any:
    return func.regexp_replace(func.coalesce(column, ""), "[^0-9]+", "", "g")


def _column_matches(column: Any, identities: Sequence[str]) -> ColumnElement[bool]:
    digits = _digit_expr(column)
    clauses: list[ColumnElement[bool]] = []
    for ident in identities:
        clauses.append(digits == ident)
        if len(ident) >= _MOBILE_MIN_DIGITS:
            last10 = ident[-_MOBILE_MIN_DIGITS:]
            clauses.append(
                and_(func.length(digits) >= _MOBILE_MIN_DIGITS, func.right(digits, 10) == last10)
            )
    return or_(*clauses)


def call_party_filter(identities: Sequence[str]) -> ColumnElement[bool]:
    if not identities:
        return false()
    return or_(
        _column_matches(Call.caller_number, identities),
        _column_matches(Call.dialed_number, identities),
        _column_matches(Call.agent_extension, identities),
    )


def apply_operator_scope(stmt: Select[Any], principal: Principal) -> Select[Any]:
    if not is_operator(principal):
        return stmt
    assignment_exists = (
        select(CallOperatorAssignment.id)
        .where(
            CallOperatorAssignment.tenant_id == principal.tenant_id,
            CallOperatorAssignment.call_id == Call.id,
            CallOperatorAssignment.operator_id == principal.id,
            CallOperatorAssignment.superseded_at.is_(None),
        )
        .exists()
    )
    return stmt.where(assignment_exists)


def operator_window(principal: Principal, window: ColumnElement[bool]) -> ColumnElement[bool]:
    if not is_operator(principal):
        return window
    assignment_exists = (
        select(CallOperatorAssignment.id)
        .where(
            CallOperatorAssignment.tenant_id == principal.tenant_id,
            CallOperatorAssignment.call_id == Call.id,
            CallOperatorAssignment.operator_id == principal.id,
            CallOperatorAssignment.superseded_at.is_(None),
        )
        .exists()
    )
    return and_(window, assignment_exists)


def assert_call_visible(call: Call, principal: Principal) -> None:
    if not is_operator(principal):
        return
    if call_visible_to_operator(
        call, mobile_number=principal.mobile_number, extension=principal.extension
    ):
        return
    raise ApiError("not_found", "call not found")


def require_operator_numbers(
    *, role: str, mobile_number: str | None, extension: str | None
) -> None:
    if role != "operator":
        return
    if identities_of(mobile_number=mobile_number, extension=extension):
        return
    raise ApiError(
        "invalid_request", "an operator must have a mobile number or an internal extension"
    )


def identities_conflict(
    left_mobile: str | None,
    left_extension: str | None,
    right_mobile: str | None,
    right_extension: str | None,
) -> bool:
    left = set(identities_of(mobile_number=left_mobile, extension=left_extension))
    right = set(identities_of(mobile_number=right_mobile, extension=right_extension))
    if left & right:
        return True
    left_mobiles = {ident[-10:] for ident in left if len(ident) >= _MOBILE_MIN_DIGITS}
    right_mobiles = {ident[-10:] for ident in right if len(ident) >= _MOBILE_MIN_DIGITS}
    return bool(left_mobiles & right_mobiles)


async def assert_unique_operator_numbers(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    mobile_number: str | None,
    extension: str | None,
    exclude_user_id: UUID | None = None,
) -> None:
    if not identities_of(mobile_number=mobile_number, extension=extension):
        return
    stmt = select(User).where(User.tenant_id == tenant_id)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    others = (await session.execute(stmt)).scalars().all()
    for other in others:
        if identities_conflict(mobile_number, extension, other.mobile_number, other.extension):
            raise ApiError(
                "conflict_idempotency",
                "this mobile number or extension is already assigned to another user",
            )


async def assert_call_visible_canonical(
    session: AsyncSession, call: Call, principal: Principal
) -> None:
    if not is_operator(principal):
        return
    assignment = (
        await session.execute(
            select(CallOperatorAssignment.id).where(
                CallOperatorAssignment.tenant_id == principal.tenant_id,
                CallOperatorAssignment.call_id == call.id,
                CallOperatorAssignment.operator_id == principal.id,
                CallOperatorAssignment.superseded_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise ApiError("not_found", "call not found")


async def assert_operator_quota(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    extra: int = 1,
    exclude_user_id: UUID | None = None,
) -> None:
    if get_settings().tenant_databases_enabled:
        from app.db import session_scope

        async with session_scope(tenant_id) as tenant_session:
            entitlement = await entitlements.require_consumption(tenant_session, tenant_id)
    else:
        entitlement = await entitlements.require_consumption(session, tenant_id)
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.tenant_id == tenant_id, User.role == "operator")
    )
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    used = int((await session.execute(stmt)).scalar_one())
    if used + extra > entitlement.max_operators:
        raise ApiError(
            "quota_exceeded",
            f"this organization may have at most {entitlement.max_operators} operators",
        )
