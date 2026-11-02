"""Who may see a meeting: its owner, plus every org_admin of the tenant."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Select

from app.models import Meeting

if TYPE_CHECKING:
    from app.deps import Principal


def actor_user_id(principal: Principal) -> UUID:
    """The user behind a JWT or a personal mobile token."""
    user_id = principal.user_id if principal.kind == "api_key" else principal.id
    if user_id is None:
        raise ValueError("principal has no user")
    return user_id


def sees_all(principal: Principal) -> bool:
    return principal.kind == "user" and principal.role == "org_admin"


def apply_meeting_scope[T: tuple[Any, ...]](stmt: Select[T], principal: Principal) -> Select[T]:
    """Tenant boundary plus the owner rule; org_admin keeps the whole tenant."""
    stmt = stmt.where(Meeting.tenant_id == principal.tenant_id)
    if sees_all(principal):
        return stmt
    return stmt.where(Meeting.owner_user_id == actor_user_id(principal))


def meeting_visible(meeting: Meeting, principal: Principal) -> bool:
    if meeting.tenant_id != principal.tenant_id:
        return False
    return sees_all(principal) or meeting.owner_user_id == actor_user_id(principal)
