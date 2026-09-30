from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import session_scope
from app.errors import ApiError
from app.logging import log_context
from app.models import ApiKey, StaffUser, Tenant, User
from app.security import decode_access_token, hash_api_key
from app.services import ratelimit

PrincipalKind = Literal["user", "staff", "api_key"]


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    id: UUID
    tenant_id: UUID | None
    role: str
    mobile_number: str | None = None
    extension: str | None = None


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError("unauthorized", "missing bearer token")
    return authorization.split(" ", 1)[1].strip()


async def current_user(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    token = _bearer(authorization)
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise ApiError("unauthorized", f"invalid token: {exc}") from exc
    if claims.get("actor") != "user" or not claims.get("tenant_id"):
        raise ApiError("unauthorized", "tenant token required")

    tenant_id = UUID(str(claims["tenant_id"]))
    async with session_scope(None, staff=True) as session:
        user = await session.get(User, UUID(str(claims["sub"])))
        if user is None or user.tenant_id != tenant_id:
            raise ApiError("unauthorized", "user no longer exists")
        principal = Principal(
            kind="user",
            id=user.id,
            tenant_id=tenant_id,
            role=user.role,
            mobile_number=user.mobile_number,
            extension=user.extension,
        )
    await _assert_tenant_active(tenant_id)
    log_context(tenant_id=str(principal.tenant_id))
    request.state.principal = principal
    await ratelimit.enforce(f"user:{principal.id}", get_settings().rate_limit_reads_per_minute)
    return principal


async def current_staff(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    token = _bearer(authorization)
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise ApiError("unauthorized", f"invalid token: {exc}") from exc
    if claims.get("actor") != "staff":
        raise ApiError("forbidden", "staff token required")

    principal = Principal(
        kind="staff", id=UUID(str(claims["sub"])), tenant_id=None, role=str(claims["role"])
    )
    async with session_scope(None, staff=True) as session:
        staff = await session.get(StaffUser, principal.id)
        if staff is None or staff.disabled_at is not None:
            raise ApiError("unauthorized", "staff user no longer exists")
    request.state.principal = principal
    return principal


async def current_api_key(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    secret: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        secret = authorization.split(" ", 1)[1].strip() or None
    if not secret and x_api_key:
        secret = x_api_key.strip() or None
    if not secret:
        raise ApiError("unauthorized", "missing api key")
    key_hash = hash_api_key(secret)
    async with session_scope(None, staff=True) as session:
        api_key = (
            await session.execute(
                select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
            )
        ).scalar_one_or_none()
        if api_key is None:
            raise ApiError("unauthorized", "invalid api key")
        await session.execute(
            update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=datetime.now(UTC))
        )
        tenant_id = api_key.tenant_id
        key_id = api_key.id

    await _assert_tenant_active(tenant_id)
    log_context(tenant_id=str(tenant_id))
    principal = Principal(kind="api_key", id=key_id, tenant_id=tenant_id, role="agent")
    request.state.principal = principal
    await ratelimit.enforce(f"key:{key_id}", get_settings().rate_limit_uploads_per_minute)
    return principal


async def _assert_tenant_active(tenant_id: UUID) -> None:
    async with session_scope(None, staff=True) as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ApiError("unauthorized", "tenant not found")
        if tenant.status != "active":
            raise ApiError("tenant_suspended", f"tenant is {tenant.status}")


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    def dependency(principal: Annotated[Principal, Depends(current_user)]) -> Principal:
        if principal.role not in roles:
            raise ApiError("forbidden", f"role {principal.role} may not perform this action")
        return principal

    return dependency


def require_staff_roles(*roles: str) -> Callable[[Principal], Principal]:
    """§12: `support` may operate tenants but not reshape the platform."""

    def dependency(principal: Annotated[Principal, Depends(current_staff)]) -> Principal:
        if principal.role not in roles:
            raise ApiError("forbidden", f"staff role {principal.role} may not perform this action")
        return principal

    return dependency


async def tenant_session(
    principal: Annotated[Principal, Depends(current_user)],
) -> AsyncIterator[AsyncSession]:
    async with session_scope(principal.tenant_id) as session:
        yield session


async def api_key_session(
    principal: Annotated[Principal, Depends(current_api_key)],
) -> AsyncIterator[AsyncSession]:
    async with session_scope(principal.tenant_id) as session:
        yield session


async def staff_session(
    principal: Annotated[Principal, Depends(current_staff)],
) -> AsyncIterator[AsyncSession]:
    async with session_scope(None, staff=True) as session:
        yield session


async def public_session() -> AsyncIterator[AsyncSession]:
    """Used by login/refresh, which must look users up before a tenant is known."""
    async with session_scope(None, staff=True) as session:
        yield session


async def control_session(
    principal: Annotated[Principal, Depends(current_user)],
) -> AsyncIterator[AsyncSession]:
    async with session_scope(None, staff=True) as session:
        yield session


UserDep = Annotated[Principal, Depends(current_user)]
OrgAdminDep = Annotated[Principal, Depends(require_roles("org_admin"))]
OperatorDep = Annotated[Principal, Depends(require_roles("org_admin", "operator"))]
StaffDep = Annotated[Principal, Depends(current_staff)]
SuperAdminDep = StaffDep
ApiKeyDep = Annotated[Principal, Depends(current_api_key)]
TenantSession = Annotated[AsyncSession, Depends(tenant_session)]
ApiKeySession = Annotated[AsyncSession, Depends(api_key_session)]
StaffSession = Annotated[AsyncSession, Depends(staff_session)]
PublicSession = Annotated[AsyncSession, Depends(public_session)]
ControlSession = Annotated[AsyncSession, Depends(control_session)]


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
