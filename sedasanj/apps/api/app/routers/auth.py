from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import ControlSession, OrgAdminDep, PublicSession, UserDep, client_ip
from app.errors import ApiError
from app.models import ApiKey, RefreshToken, Tenant, User
from app.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ApiKeyUpdate,
    ArchiveFormat,
    CustomerLoginRequest,
    LoginStep,
    MemberAccountLink,
    MemberEmailChange,
    MemberPasswordReset,
    ProfileUpdate,
    RefreshRequest,
    TokenPair,
    TotpCheck,
    TotpDisable,
    TotpSetup,
    TotpStatus,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.security import (
    create_access_token,
    generate_api_key,
    generate_refresh_token,
    generate_totp_secret,
    hash_password,
    hash_refresh_token,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.services import (
    audit,
    extensions,
    identity_projection,
    member_account_actions,
    operator_scope,
    ratelimit,
)
from app.services.phone_identity import mobile_accounts, normalize_mobile

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _token_pair(access: str, refresh: str) -> TokenPair:
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=get_settings().access_token_ttl_minutes * 60,
    )


async def _password_user(
    payload: CustomerLoginRequest, session: AsyncSession, rate_bucket: str, ip: str | None
) -> User:
    await ratelimit.enforce(f"{rate_bucket}-ip:{ip}", 60)
    identifier = payload.identifier
    is_email = "@" in identifier
    if is_email:
        identifier = identifier.lower()
        await ratelimit.enforce(f"{rate_bucket}:{identifier}", 10)
        candidates = (
            (await session.execute(select(User).where(User.email == identifier))).scalars().all()
        )
        user = next(
            (
                candidate
                for candidate in candidates
                if verify_password(candidate.password_hash, payload.password)
            ),
            None,
        )
    else:
        identifier = normalize_mobile(identifier)
        await ratelimit.enforce(f"{rate_bucket}:{identifier}", 10)
        matches = [
            candidate
            for candidate, _ in await mobile_accounts(session, identifier)
            if verify_password(candidate.password_hash, payload.password)
        ]
        if len(matches) > 1:
            raise ApiError(
                "login_mobile_ambiguous",
                "این شماره و گذرواژه برای چند حساب یکسان است. با ایمیل حساب موردنظر وارد شوید.",
            )
        user = next(iter(matches), None)
    if user is None:
        raise ApiError("unauthorized", "ایمیل، شماره موبایل یا گذرواژه را بررسی کنید.")
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None or tenant.status != "active":
        raise ApiError("tenant_suspended", "حساب سازمانی فعال نیست؛ با پشتیبانی تماس بگیرید.")
    return user


@router.post("/check", response_model=LoginStep)
async def check_login(
    payload: CustomerLoginRequest, request: Request, session: PublicSession
) -> LoginStep:
    user = await _password_user(payload, session, "login-check", client_ip(request))
    return LoginStep(requires_totp=bool(user.totp_secret))


@router.get("/totp", response_model=TotpStatus)
async def totp_status(session: ControlSession, principal: OrgAdminDep) -> TotpStatus:
    account = await session.get(User, principal.id)
    return TotpStatus(enabled=bool(account and account.totp_secret))


@router.post("/totp/setup", response_model=TotpSetup)
async def totp_setup(session: ControlSession, principal: OrgAdminDep) -> TotpSetup:
    account = await session.get(User, principal.id, with_for_update=True)
    if account is None or account.totp_secret:
        raise ApiError("invalid_request", "two-factor authentication is already enabled")
    account.totp_pending_secret = generate_totp_secret()
    return TotpSetup(
        secret=account.totp_pending_secret, uri=totp_uri(account.totp_pending_secret, account.email)
    )


@router.post("/totp/enable", response_model=TotpStatus)
async def totp_enable(
    payload: TotpCheck, session: ControlSession, principal: OrgAdminDep
) -> TotpStatus:
    account = await session.get(User, principal.id, with_for_update=True)
    if account is None or account.totp_secret or not account.totp_pending_secret:
        raise ApiError("invalid_request", "start two-factor setup first")
    if not verify_totp(account.totp_pending_secret, payload.code):
        raise ApiError("unauthorized", "two-factor code is invalid")
    account.totp_secret = account.totp_pending_secret
    account.totp_pending_secret = None
    return TotpStatus(enabled=True)


@router.post("/totp/disable", response_model=TotpStatus)
async def totp_disable(
    payload: TotpDisable, session: ControlSession, principal: OrgAdminDep
) -> TotpStatus:
    account = await session.get(User, principal.id, with_for_update=True)
    if (
        account is None
        or not account.totp_secret
        or not verify_password(account.password_hash, payload.password)
        or not verify_totp(account.totp_secret, payload.code)
    ):
        raise ApiError("unauthorized", "password or two-factor code is invalid")
    account.totp_secret = None
    account.totp_pending_secret = None
    return TotpStatus(enabled=False)


@router.post("/login", response_model=TokenPair)
async def login(
    payload: CustomerLoginRequest, request: Request, session: PublicSession
) -> TokenPair:
    user = await _password_user(payload, session, "login", client_ip(request))
    password_hash = user.password_hash
    current = await session.get(User, user.id, with_for_update=True, populate_existing=True)
    if current is None or current.password_hash != password_hash:
        raise ApiError("unauthorized", "گذرواژه را دوباره وارد کنید.")
    user = current
    if user.totp_secret and not verify_totp(user.totp_secret, payload.totp_code):
        raise ApiError("unauthorized", "کد ورود دومرحله‌ای را دوباره وارد کنید.")

    settings = get_settings()
    token, token_hash = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await audit.record(
        session,
        actor_type="user",
        actor_id=user.id,
        tenant_id=user.tenant_id,
        action="auth.login",
        ip=client_ip(request),
    )
    access = create_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role)
    return _token_pair(access, token)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: PublicSession) -> TokenPair:
    token_hash = hash_refresh_token(payload.refresh_token)
    user_id = await session.scalar(
        select(RefreshToken.user_id).where(RefreshToken.token_hash == token_hash)
    )
    if user_id is None:
        raise ApiError("unauthorized", "refresh token is not usable")
    # Lock the account first so password changes can revoke refresh tokens atomically.
    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise ApiError("unauthorized", "user no longer exists")
    stored = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )
    now = datetime.now(UTC)
    if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
        raise ApiError("unauthorized", "refresh token is not usable")

    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None or tenant.status != "active":
        raise ApiError("tenant_suspended", "tenant is not active")

    settings = get_settings()
    stored.revoked_at = now
    new_token, new_hash = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=new_hash,
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    access = create_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role)
    return _token_pair(access, new_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, session: PublicSession) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(payload.refresh_token))
        .values(revoked_at=datetime.now(UTC))
    )


def _created_out(row: ApiKey, secret: str) -> ApiKeyCreated:
    return ApiKeyCreated(
        **_api_key_out(row).model_dump(exclude={"created_at"}),
        created_at=row.created_at or datetime.now(UTC),
        secret=secret,
    )


def _api_key_out(row: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id,
        key_prefix=row.key_prefix,
        label=row.label,
        archive_format=cast(ArchiveFormat, row.archive_format),
        archive_password_configured=row.archive_password_hash is not None,
        scopes=list(row.scopes),
        expires_at=row.expires_at,
        allowed_cidrs=list(row.allowed_cidrs),
        last_used_at=row.last_used_at,
        last_used_ip=str(row.last_used_ip) if row.last_used_ip is not None else None,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
) -> ApiKeyCreated:
    secret, prefix, key_hash = generate_api_key()
    assert principal.tenant_id is not None
    api_key = ApiKey(
        tenant_id=principal.tenant_id,
        key_hash=key_hash,
        key_prefix=prefix,
        label=payload.label,
        archive_format=payload.archive_format,
        archive_password_hash=(
            await asyncio.to_thread(hash_password, payload.archive_password)
            if payload.archive_password
            else None
        ),
        scopes=list(payload.scopes),
        expires_at=payload.expires_at,
        allowed_cidrs=payload.allowed_cidrs,
    )
    session.add(api_key)
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="api_key.create",
        payload={
            "api_key_id": str(api_key.id),
            "label": payload.label,
            "archive_format": payload.archive_format,
            "archive_password_configured": payload.archive_password is not None,
            "scopes": payload.scopes,
            "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
            "allowed_cidrs": payload.allowed_cidrs,
        },
        ip=client_ip(request),
    )
    return _created_out(api_key, secret)


@router.get("/api-keys")
async def list_api_keys(
    session: ControlSession,
    principal: OrgAdminDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    include_revoked: bool = False,
) -> dict[str, Any]:
    base = select(ApiKey).where(
        ApiKey.tenant_id == principal.tenant_id, ApiKey.kind == "integration"
    )
    if not include_revoked:
        base = base.where(ApiKey.revoked_at.is_(None))
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base
            .order_by(ApiKey.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    items = [_api_key_out(row) for row in rows]
    return {"items": items, "total": total, "next_cursor": str(offset + limit) if offset + len(items) < total else None}


@router.patch("/api-keys/{key_id}", response_model=ApiKeyOut)
async def update_api_key(
    key_id: UUID,
    payload: ApiKeyUpdate,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
) -> ApiKeyOut:
    api_key = await session.get(ApiKey, key_id)
    if (
        api_key is None
        or api_key.tenant_id != principal.tenant_id
        or api_key.revoked_at is not None
        or api_key.kind != "integration"
    ):
        raise ApiError("not_found", "api key not found")

    changes = payload.model_fields_set
    if "label" in changes:
        api_key.label = payload.label
    if payload.archive_format is not None:
        api_key.archive_format = payload.archive_format
        if payload.archive_format == "gzip":
            api_key.archive_password_hash = None
    if payload.archive_password is not None:
        if (payload.archive_format or api_key.archive_format) != "zip":
            raise ApiError("invalid_request", "archive_password is only supported for zip")
        api_key.archive_password_hash = await asyncio.to_thread(
            hash_password, payload.archive_password
        )
    if payload.remove_archive_password:
        api_key.archive_password_hash = None
    if payload.scopes is not None:
        api_key.scopes = list(payload.scopes)
    if "expires_at" in changes:
        api_key.expires_at = payload.expires_at
    if payload.allowed_cidrs is not None:
        api_key.allowed_cidrs = payload.allowed_cidrs

    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="api_key.update",
        payload={
            "api_key_id": str(api_key.id),
            "label_changed": "label" in changes,
            "archive_format": api_key.archive_format,
            "scopes": api_key.scopes,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            "allowed_cidrs": api_key.allowed_cidrs,
            "archive_password_action": (
                "removed"
                if payload.remove_archive_password or payload.archive_format == "gzip"
                else "set"
                if payload.archive_password is not None
                else "unchanged"
            ),
        },
        ip=client_ip(request),
    )
    return _api_key_out(api_key)


@router.post(
    "/api-keys/{key_id}/rotate",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_api_key(
    key_id: UUID,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
    grace_hours: Annotated[int, Query(ge=0, le=168)] = 24,
) -> ApiKeyCreated:
    """Issue a replacement with the same settings; the old key stops after `grace_hours`."""
    old = await session.get(ApiKey, key_id)
    if (
        old is None
        or old.tenant_id != principal.tenant_id
        or old.revoked_at is not None
        or old.kind != "integration"
    ):
        raise ApiError("not_found", "api key not found")
    secret, prefix, key_hash = generate_api_key()
    new = ApiKey(
        tenant_id=old.tenant_id,
        key_hash=key_hash,
        key_prefix=prefix,
        label=old.label,
        archive_format=old.archive_format,
        archive_password_hash=old.archive_password_hash,
        scopes=list(old.scopes),
        expires_at=old.expires_at,
        allowed_cidrs=list(old.allowed_cidrs),
    )
    session.add(new)
    now = datetime.now(UTC)
    if grace_hours == 0:
        old.revoked_at = now
    else:
        cutoff = now + timedelta(hours=grace_hours)
        old.expires_at = cutoff if old.expires_at is None else min(old.expires_at, cutoff)
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="api_key.rotate",
        payload={
            "old_api_key_id": str(old.id),
            "new_api_key_id": str(new.id),
            "grace_hours": grace_hours,
        },
        ip=client_ip(request),
    )
    return _created_out(new, secret)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: UUID,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
) -> None:
    revoked = await session.execute(
        update(ApiKey)
        .where(
            ApiKey.id == key_id,
            ApiKey.tenant_id == principal.tenant_id,
            ApiKey.kind == "integration",
            ApiKey.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
        .returning(ApiKey.id)
    )
    if revoked.scalar_one_or_none() is None:
        raise ApiError("not_found", "api key not found")
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="api_key.revoke",
        payload={"api_key_id": str(key_id)},
        ip=client_ip(request),
    )


@router.get("/me", response_model=UserOut)
async def me(session: ControlSession, principal: UserDep) -> UserOut:
    user = await session.get(User, principal.id)
    if user is None:
        raise ApiError("unauthorized", "user no longer exists")
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: ProfileUpdate,
    request: Request,
    session: ControlSession,
    principal: UserDep,
) -> UserOut:
    user = await session.get(User, principal.id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise ApiError("unauthorized", "user no longer exists")
    if user.role == "operator" and payload.extension != user.extension:
        raise ApiError("forbidden", "برای تغییر داخلی با مدیر سازمان تماس بگیرید")
    operator_scope.require_operator_numbers(
        role=user.role,
        mobile_number=payload.mobile_number,
        extension=payload.extension,
    )
    await operator_scope.assert_unique_operator_numbers(
        session,
        user.tenant_id,
        mobile_number=payload.mobile_number,
        extension=payload.extension,
        exclude_user_id=user.id,
    )
    user.display_name = payload.display_name
    user.mobile_number = payload.mobile_number
    user.extension = payload.extension
    user.profile_context = payload.profile_context
    await session.flush()
    await identity_projection.stage_user_projection(session, user)
    await audit.record(
        session,
        actor_type="user",
        actor_id=user.id,
        tenant_id=user.tenant_id,
        action="user.profile_update",
        payload={"user_id": str(user.id)},
        ip=client_ip(request),
    )
    return UserOut.model_validate(user)


@router.get("/users")
async def list_users(
    session: ControlSession,
    principal: OrgAdminDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> dict[str, Any]:
    base = select(User).where(User.tenant_id == principal.tenant_id)
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base.order_by(User.created_at).offset(offset).limit(limit)
        )
    ).scalars().all()
    items = [UserOut.model_validate(row) for row in rows]
    return {"items": items, "total": total, "next_cursor": str(offset + limit) if offset + len(items) < total else None}


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
) -> UserOut:
    assert principal.tenant_id is not None
    existing = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError("conflict_idempotency", "a user with this email already exists")
    if payload.role == "operator":
        await operator_scope.assert_operator_quota(session, principal.tenant_id)
    operator_scope.require_operator_numbers(
        role=payload.role, mobile_number=payload.mobile_number, extension=payload.extension
    )
    await operator_scope.assert_unique_operator_numbers(
        session,
        principal.tenant_id,
        mobile_number=payload.mobile_number,
        extension=payload.extension,
    )
    if not get_settings().tenant_databases_enabled:
        await extensions.lock_inventory(session, principal.tenant_id)
    user = User(
        tenant_id=principal.tenant_id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        mobile_number=payload.mobile_number,
        extension=payload.extension,
        display_name=payload.display_name,
    )
    session.add(user)
    await session.flush()
    await identity_projection.stage_user_projection(session, user, reconcile_extension=True)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="user.create",
        payload={"user_id": str(user.id), "role": payload.role},
        ip=client_ip(request),
    )
    return UserOut.model_validate(user)


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: UUID,
    session: ControlSession,
    principal: OrgAdminDep,
) -> UserOut:
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise ApiError("not_found", "user not found")
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/email-change", status_code=status.HTTP_204_NO_CONTENT)
async def request_member_email_change(
    user_id: UUID,
    payload: MemberEmailChange,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
) -> None:
    user = await _member_for_account_action(session, principal.tenant_id, user_id, request)
    if user.role == "org_admin":
        raise ApiError("forbidden", "برای تغییر ایمیل حساب مدیر با پشتیبانی تماس بگیرید.")
    if await session.scalar(select(User.id).where(User.email == payload.email).limit(1)):
        raise ApiError(
            "conflict_idempotency", "این ایمیل در حال استفاده است؛ ایمیل دیگری وارد کنید."
        )
    await member_account_actions.issue(session, user, principal.id, "email", payload.email)


@router.post("/users/{user_id}/password-reset", status_code=status.HTTP_204_NO_CONTENT)
async def request_member_password_reset(
    user_id: UUID,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
) -> None:
    user = await _member_for_account_action(session, principal.tenant_id, user_id, request)
    await member_account_actions.issue(session, user, principal.id, "password", user.email)


async def _member_for_account_action(
    session: AsyncSession, tenant_id: UUID | None, user_id: UUID, request: Request
) -> User:
    await ratelimit.enforce(f"member-account-send-ip:{client_ip(request)}", 20, 3600)
    user = await session.get(User, user_id, with_for_update=True)
    if user is None or user.tenant_id != tenant_id:
        raise ApiError("not_found", "user not found")
    await ratelimit.enforce(f"member-account-send:{user_id}", 6, 3600)
    return user


@router.post("/member-email-change/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_member_email_change(
    payload: MemberAccountLink, request: Request, session: PublicSession
) -> None:
    await ratelimit.enforce(f"member-account-confirm:{client_ip(request)}", 15)
    user, actor_id, email = await member_account_actions.consume(session, "email", payload.token)
    if await session.scalar(select(User.id).where(User.email == email).limit(1)):
        raise ApiError("conflict_idempotency", "این ایمیل در حال استفاده است؛ پیوند تازه بگیرید.")
    user.email = email
    await _finish_member_account_change(session, user, actor_id, "user.email_change", request)


@router.post("/member-password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_member_password_reset(
    payload: MemberPasswordReset, request: Request, session: PublicSession
) -> None:
    await ratelimit.enforce(f"member-account-confirm:{client_ip(request)}", 15)
    user, actor_id, _ = await member_account_actions.consume(session, "password", payload.token)
    user.password_hash = await asyncio.to_thread(hash_password, payload.password)
    await _finish_member_account_change(session, user, actor_id, "user.password_reset", request)


async def _finish_member_account_change(
    session: AsyncSession, user: User, actor_id: UUID, action: str, request: Request
) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.flush()
    await identity_projection.stage_user_projection(session, user)
    await audit.record(
        session,
        actor_type="user",
        actor_id=actor_id,
        tenant_id=user.tenant_id,
        action=action,
        payload={"user_id": str(user.id)},
        ip=client_ip(request),
    )


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
) -> UserOut:
    assert principal.tenant_id is not None
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise ApiError("not_found", "user not found")
    changes = payload.model_dump(exclude_unset=True)
    next_role = str(changes.get("role", user.role))
    next_mobile = changes.get("mobile_number", user.mobile_number)
    next_extension = changes.get("extension", user.extension)
    becoming_operator = user.role != "operator" and next_role == "operator"
    if becoming_operator:
        await operator_scope.assert_operator_quota(session, principal.tenant_id)
    operator_scope.require_operator_numbers(
        role=next_role, mobile_number=next_mobile, extension=next_extension
    )
    await operator_scope.assert_unique_operator_numbers(
        session,
        principal.tenant_id,
        mobile_number=next_mobile,
        extension=next_extension,
        exclude_user_id=user.id,
    )
    if "password" in changes:
        raise ApiError(
            "invalid_request", "برای تغییر گذرواژه از اقدام «بازنشانی گذرواژه» استفاده کنید."
        )
    reconcile_extension = "extension" in changes or next_role != user.role
    if reconcile_extension and not get_settings().tenant_databases_enabled:
        await extensions.lock_inventory(session, principal.tenant_id)
    for field, value in changes.items():
        setattr(user, field, value)
    await session.flush()
    await identity_projection.stage_user_projection(
        session, user, reconcile_extension=reconcile_extension
    )
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="user.update",
        payload={"user_id": str(user.id), "role": user.role},
        ip=client_ip(request),
    )
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    request: Request,
    session: ControlSession,
    principal: OrgAdminDep,
) -> None:
    if user_id == principal.id:
        raise ApiError("forbidden", "you cannot delete your own account")
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise ApiError("not_found", "user not found")
    await identity_projection.stage_user_projection(session, user, operation="delete")
    await session.delete(user)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="user.delete",
        payload={"user_id": str(user_id)},
        ip=client_ip(request),
    )
