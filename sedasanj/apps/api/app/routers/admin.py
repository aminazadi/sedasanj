from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings, normalize_api_key
from app.db import (
    operational_tenant_ids,
    resolve_tenant_for_job,
    routable_tenant_ids,
    session_scope,
)
from app.deps import PublicSession, StaffDep, StaffSession, SuperAdminDep, client_ip
from app.errors import ApiError
from app.models import (
    AnalysisRun,
    AuditEvent,
    Call,
    CallKnowledge,
    Job,
    JobOutbox,
    LedgerEntry,
    Package,
    Plan,
    PlanVersion,
    PlatformSetting,
    StaffRefreshToken,
    StaffUser,
    Subscription,
    Tenant,
    TenantBackup,
    TenantBalanceCache,
    TenantDatabaseRegistry,
    TenantDataMigration,
    Transcript,
    TranscriptChunk,
    User,
)
from app.schemas import (
    AuditEventOut,
    JobOut,
    KnowledgeRetryRequest,
    LoginRequest,
    LoginStep,
    NineRouterConnectionInput,
    PackageCreate,
    PackageOut,
    PackageUpdate,
    PlatformKpis,
    ProviderModelOut,
    RefreshRequest,
    SettingsUpdate,
    StaffCreate,
    StaffPasswordReset,
    StaffSensitiveAction,
    TenantCreate,
    TenantDetail,
    TenantOut,
    TenantUpdate,
    TokenPair,
    TopupCreate,
    TotpCheck,
    TotpDisable,
    TotpSetup,
    TotpStatus,
    UserOut,
)
from app.security import (
    create_access_token,
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
    billing,
    knowledge,
    outbox,
    processing_events,
    progress,
    queue,
    ratelimit,
)
from app.services.audio import DENOISER_MODELS, ENHANCEMENT_MODELS
from app.services.ninerouter import NineRouterClient
from app.services.platform import (
    EXTRACT_PROMPT_KEY,
    capability_model,
    effective_extract_prompt,
    effective_models,
    normalize_provider_base_url,
    resolve_provider_settings,
    settings_public_view,
)
from app.services.platform_secrets import decrypt_secret, encrypt_secret
from app.services.provider_errors import ProviderError
from app.services.tenant_provisioning import rollback_tenant
from app.services.transcript_corrections import CorrectionClient, validate_result
from app.services.voicesanj import VoiceSanjClient
from worker_llm.client import available_prompt_versions

router = APIRouter(prefix="/v1/admin", tags=["admin"])
logger = logging.getLogger(__name__)

QUEUE_BY_KIND = {
    "asr": (queue.QUEUE_ASR, queue.JOB_ASR),
    "emotion": (queue.QUEUE_EMOTION, queue.JOB_EMOTION),
    "llm": (queue.QUEUE_LLM, queue.JOB_LLM),
    "notify": (queue.QUEUE_NOTIFY, queue.JOB_NOTIFY),
}


async def _verify_sensitive_staff_action(
    session: AsyncSession, principal: Any, current_password: str, totp_code: str | None
) -> StaffUser:
    account = await session.get(StaffUser, principal.id)
    if account is None or not verify_password(account.password_hash, current_password):
        raise ApiError("unauthorized", "current password is invalid")
    if account.totp_secret and not verify_totp(account.totp_secret, totp_code):
        raise ApiError("unauthorized", "two-factor code is invalid")
    return account


@router.post("/auth/check", response_model=LoginStep)
async def check_login(payload: LoginRequest, session: PublicSession) -> LoginStep:
    await ratelimit.enforce(f"staff-login-check:{payload.email.lower()}", 10)
    staff = (
        await session.execute(select(StaffUser).where(StaffUser.email == payload.email))
    ).scalar_one_or_none()
    if staff is None or staff.disabled_at is not None or not verify_password(staff.password_hash, payload.password):
        raise ApiError("unauthorized", "email or password is incorrect")

    return LoginStep(requires_totp=bool(staff.totp_secret))


@router.get("/auth/totp", response_model=TotpStatus)
async def totp_status(session: StaffSession, principal: StaffDep) -> TotpStatus:
    account = await session.get(StaffUser, principal.id)
    return TotpStatus(enabled=bool(account and account.totp_secret))


@router.post("/auth/totp/setup", response_model=TotpSetup)
async def totp_setup(session: StaffSession, principal: StaffDep) -> TotpSetup:
    account = await session.get(StaffUser, principal.id, with_for_update=True)
    if account is None or account.totp_secret:
        raise ApiError("invalid_request", "two-factor authentication is already enabled")
    account.totp_pending_secret = generate_totp_secret()
    return TotpSetup(
        secret=account.totp_pending_secret, uri=totp_uri(account.totp_pending_secret, account.email)
    )


@router.post("/auth/totp/enable", response_model=TotpStatus)
async def totp_enable(payload: TotpCheck, session: StaffSession, principal: StaffDep) -> TotpStatus:
    account = await session.get(StaffUser, principal.id, with_for_update=True)
    if account is None or account.totp_secret or not account.totp_pending_secret:
        raise ApiError("invalid_request", "start two-factor setup first")
    if not verify_totp(account.totp_pending_secret, payload.code):
        raise ApiError("unauthorized", "two-factor code is invalid")
    account.totp_secret = account.totp_pending_secret
    account.totp_pending_secret = None
    return TotpStatus(enabled=True)


@router.post("/auth/totp/disable", response_model=TotpStatus)
async def totp_disable(
    payload: TotpDisable, session: StaffSession, principal: StaffDep
) -> TotpStatus:
    account = await session.get(StaffUser, principal.id, with_for_update=True)
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


@router.post("/auth/login", response_model=TokenPair)
async def staff_login(payload: LoginRequest, request: Request, session: PublicSession) -> TokenPair:
    await ratelimit.enforce(f"staff-login:{payload.email.lower()}", 10)
    staff = (
        await session.execute(select(StaffUser).where(StaffUser.email == payload.email))
    ).scalar_one_or_none()
    if staff is None or staff.disabled_at is not None or not verify_password(staff.password_hash, payload.password):
        raise ApiError("unauthorized", "email or password is incorrect")

    if staff.totp_secret and not verify_totp(staff.totp_secret, payload.totp_code):
        raise ApiError("unauthorized", "two-factor code is invalid")

    settings = get_settings()
    token, token_hash = generate_refresh_token()
    session.add(
        StaffRefreshToken(
            staff_user_id=staff.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="staff.login",
        ip=client_ip(request),
    )
    access = create_access_token(subject=staff.id, tenant_id=None, role=staff.role, actor="staff")
    return TokenPair(
        access_token=access,
        refresh_token=token,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/auth/refresh", response_model=TokenPair)
async def staff_refresh(payload: RefreshRequest, session: PublicSession) -> TokenPair:
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = (
        await session.execute(
            select(StaffRefreshToken)
            .where(StaffRefreshToken.token_hash == token_hash)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
        raise ApiError("unauthorized", "refresh token is not usable")
    staff = await session.get(StaffUser, stored.staff_user_id)
    if staff is None or staff.disabled_at is not None:
        raise ApiError("unauthorized", "staff user no longer exists")

    settings = get_settings()
    stored.revoked_at = now
    token, new_hash = generate_refresh_token()
    session.add(
        StaffRefreshToken(
            staff_user_id=staff.id,
            token_hash=new_hash,
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    return TokenPair(
        access_token=create_access_token(
            subject=staff.id, tenant_id=None, role=staff.role, actor="staff"
        ),
        refresh_token=token,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def staff_logout(payload: RefreshRequest, session: PublicSession) -> None:
    await session.execute(
        update(StaffRefreshToken)
        .where(StaffRefreshToken.token_hash == hash_refresh_token(payload.refresh_token))
        .values(revoked_at=datetime.now(UTC))
    )


@router.get("/kpis", response_model=PlatformKpis)
async def kpis(staff: StaffDep, session: StaffSession) -> PlatformKpis:
    since = datetime.now(UTC) - timedelta(days=1)
    tenants_active = int(
        (
            await session.execute(select(func.count(Tenant.id)).where(Tenant.status == "active"))
        ).scalar_one()
    )
    calls_today = 0
    minutes_ms = 0
    calls_failed = 0
    jobs_failed = 0
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            tenant_calls, tenant_minutes = (
                await tenant_session.execute(
                    select(
                        func.count(Call.id),
                        func.coalesce(func.sum(Call.duration_ms), 0),
                    ).where(
                        Call.tenant_id == tenant_id,
                        Call.created_at >= since,
                    )
                )
            ).one()
            calls_today += int(tenant_calls)
            minutes_ms += int(tenant_minutes)
            calls_failed += int(
                (
                    await tenant_session.execute(
                        select(func.count(Call.id)).where(
                            Call.tenant_id == tenant_id,
                            Call.created_at >= since,
                            Call.status.in_(("failed_terminal", "failed_retryable")),
                        )
                    )
                ).scalar_one()
            )
            jobs_failed += int(
                (
                    await tenant_session.execute(
                        select(func.count(Job.id)).where(
                            Job.tenant_id == tenant_id,
                            Job.status == "failed_retryable",
                        )
                    )
                ).scalar_one()
            )
    q = queue.get_queue()
    depth = {
        "q:asr": await q.depth(queue.QUEUE_ASR),
        "q:emotion": await q.depth(queue.QUEUE_EMOTION),
        "q:llm": await q.depth(queue.QUEUE_LLM),
        "q:notify": await q.depth(queue.QUEUE_NOTIFY),
    }
    return PlatformKpis(
        tenants_active=tenants_active,
        calls_today=int(calls_today),
        calls_failed_today=calls_failed,
        minutes_today=round(int(minutes_ms) / 60000, 1),
        queue_depth=depth,
        jobs_failed_retryable=jobs_failed,
    )


@router.get("/tenants")
async def list_tenants(
    staff: StaffDep,
    session: StaffSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    base = select(Tenant).where(Tenant.status != "deleted")
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base.order_by(Tenant.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    return {"items": [TenantOut.model_validate(row) for row in rows], "total": total, "next_cursor": str(offset + limit) if offset + len(rows) < total else None}


@router.get("/tenant-databases")
async def list_tenant_databases(
    staff: StaffDep,
    session: StaffSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    total = int((await session.execute(select(func.count(Tenant.id)).where(Tenant.status != "deleted"))).scalar_one())
    rows = (
        await session.execute(
            select(Tenant, TenantDatabaseRegistry, TenantDataMigration)
            .outerjoin(TenantDatabaseRegistry, TenantDatabaseRegistry.tenant_id == Tenant.id)
            .outerjoin(TenantDataMigration, TenantDataMigration.tenant_id == Tenant.id)
            .where(Tenant.status != "deleted")
            .order_by(Tenant.created_at)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    latest_backups = {
        row.tenant_id: row
        for row in (
            await session.execute(
                select(TenantBackup)
                .distinct(TenantBackup.tenant_id)
                .order_by(TenantBackup.tenant_id, TenantBackup.started_at.desc())
            )
        ).scalars()
    }
    items = [
        {
            "tenant_id": str(tenant.id),
            "tenant_name": tenant.name,
            "tenant_status": tenant.status,
            "database_name": registry.database_name if registry else None,
            "database_status": registry.status if registry else "legacy",
            "schema_revision": registry.schema_revision if registry else None,
            "migration_status": migration.status if migration else None,
            "migration_phase": migration.phase if migration else None,
            "migration_error": migration.error_detail if migration else None,
            "cutover_at": migration.cutover_at if migration else None,
            "rollback_until": migration.rollback_until if migration else None,
            "backup_status": (
                latest_backups[tenant.id].status if tenant.id in latest_backups else None
            ),
            "backup_completed_at": (
                latest_backups[tenant.id].completed_at if tenant.id in latest_backups else None
            ),
            "backup_checksum": (
                latest_backups[tenant.id].checksum_sha256 if tenant.id in latest_backups else None
            ),
        }
        for tenant, registry, migration in rows
    ]
    return {"items": items, "total": total, "next_cursor": str(offset + limit) if offset + len(items) < total else None}


@router.post("/tenants/{tenant_id}/database-migration/retry", status_code=202)
async def retry_tenant_database_migration(
    tenant_id: UUID,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, str]:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError("not_found", "tenant not found")
    migration = (
        await session.execute(
            select(TenantDataMigration).where(TenantDataMigration.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if migration is None:
        migration = TenantDataMigration(tenant_id=tenant_id)
        session.add(migration)
    registry = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
    if (
        migration.status == "completed"
        and registry is not None
        and registry.status == "failed"
    ):
        registry.status = "maintenance"
        tenant.status = "maintenance_readonly"
        await audit.record(
            session,
            actor_type="staff",
            actor_id=staff.id,
            tenant_id=tenant_id,
            action="tenant_database.fleet_migration_retry",
            payload={},
            ip=client_ip(request),
        )
        return {"status": "pending"}
    migration.status = "pending"
    migration.phase = "prechecking"
    migration.error_detail = None
    if tenant.status != "active":
        tenant.status = "provisioning"
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=tenant_id,
        action="tenant_database.migration_retry",
        payload={},
        ip=client_ip(request),
    )
    return {"status": "pending"}


@router.post("/tenants/{tenant_id}/database-migration/rollback", status_code=202)
async def rollback_tenant_database_migration(
    tenant_id: UUID,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, str]:
    try:
        await rollback_tenant(tenant_id)
    except RuntimeError as exc:
        raise ApiError("invalid_request", str(exc)) from exc
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=tenant_id,
        action="tenant_database.rollback",
        payload={},
        ip=client_ip(request),
    )
    return {"status": "rolled_back"}


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate, request: Request, staff: SuperAdminDep, session: StaffSession
) -> TenantOut:
    tenant = Tenant(
        name=payload.name,
        price_per_minute_toman=payload.price_per_minute_toman,
        timezone=payload.timezone,
        audio_retention_days=payload.audio_retention_days,
        monthly_minute_quota=payload.monthly_minute_quota,
        max_concurrent_jobs=payload.max_concurrent_jobs,
        max_operators=payload.max_operators,
        status="provisioning" if get_settings().tenant_databases_enabled else "active",
    )
    session.add(tenant)
    await session.flush()
    plan_row = (
        await session.execute(
            select(Plan, PlanVersion)
            .join(PlanVersion, PlanVersion.plan_id == Plan.id)
            .where(
                Plan.code == payload.plan_code,
                Plan.active.is_(True),
                PlanVersion.status == "published",
                PlanVersion.effective_at <= datetime.now(UTC),
            )
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
    ).one_or_none()
    if plan_row is None:
        raise ApiError("not_found", "published plan not found")
    _, plan_version = plan_row
    period_start = datetime.now(UTC)
    if payload.billing_period == "legacy":
        period_end = datetime(9999, 12, 31, tzinfo=UTC)
    else:
        days = payload.subscription_days or (365 if payload.billing_period == "annual" else 30)
        period_end = period_start + timedelta(days=days)
    tenant.max_operators = plan_version.base_operators
    session.add(
        Subscription(
            tenant_id=tenant.id,
            plan_version_id=plan_version.id,
            status="active",
            billing_period=payload.billing_period,
            period_start=period_start,
            period_end=period_end,
            base_operators=plan_version.base_operators,
            extra_operators=0,
            price_per_minute_toman=payload.price_per_minute_toman,
            assistant_tier=plan_version.assistant_tier,
            assistant_monthly_messages=plan_version.assistant_monthly_messages,
            assistant_source_limit=plan_version.assistant_source_limit,
            assistant_model=plan_version.assistant_model,
        )
    )
    session.add(
        User(
            tenant_id=tenant.id,
            email=payload.admin_email,
            password_hash=hash_password(payload.admin_password),
            role="org_admin",
        )
    )
    session.add(TenantBalanceCache(tenant_id=tenant.id, seconds=0, toman=0))
    if get_settings().tenant_databases_enabled:
        session.add(TenantDataMigration(tenant_id=tenant.id))
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=tenant.id,
        action="tenant.create",
        payload={"name": payload.name, "plan_code": payload.plan_code},
        ip=client_ip(request),
    )
    return TenantOut.model_validate(tenant)


@router.get("/tenants/{tenant_id}", response_model=TenantDetail)
async def get_tenant(tenant_id: UUID, staff: StaffDep, session: StaffSession) -> TenantDetail:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError("not_found", "tenant not found")
    async with session_scope(tenant_id) as tenant_session:
        balance = await billing.get_balance(tenant_session, tenant_id)
        calls_total = int(
            (
                await tenant_session.execute(
                    select(func.count(Call.id)).where(Call.tenant_id == tenant_id)
                )
            ).scalar_one()
        )
    users = (
        await session.execute(select(User).where(User.tenant_id == tenant_id))
    ).scalars().all()
    detail = TenantDetail.model_validate(tenant)
    detail.balance_seconds = balance.seconds
    detail.balance_toman = balance.toman
    detail.calls_total = calls_total
    detail.users = [UserOut.model_validate(u) for u in users]
    return detail


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> TenantOut:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError("not_found", "tenant not found")
    changes = payload.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(tenant, field, value)
    registry_status = (
        await session.execute(
            select(TenantDatabaseRegistry.status).where(
                TenantDatabaseRegistry.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if registry_status == "ready":
        async with session_scope(tenant_id) as tenant_session:
            projection = await tenant_session.get(Tenant, tenant_id, with_for_update=True)
            if projection is None:
                raise ApiError("not_found", "tenant database identity is missing")
            for field, value in changes.items():
                setattr(projection, field, value)
            if "max_operators" in changes or "price_per_minute_toman" in changes:
                subscription = (
                    await tenant_session.execute(
                        select(Subscription)
                        .where(
                            Subscription.tenant_id == tenant_id,
                            Subscription.status.in_(("active", "trialing")),
                        )
                        .order_by(Subscription.created_at.desc())
                        .limit(1)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if subscription is not None:
                    if "max_operators" in changes:
                        subscription.base_operators = int(changes["max_operators"])
                        subscription.extra_operators = 0
                    if "price_per_minute_toman" in changes:
                        subscription.price_per_minute_toman = int(
                            changes["price_per_minute_toman"]
                        )
    elif "max_operators" in changes or "price_per_minute_toman" in changes:
        subscription = (
            await session.execute(
                select(Subscription)
                .where(
                    Subscription.tenant_id == tenant_id,
                    Subscription.status.in_(("active", "trialing")),
                )
                .order_by(Subscription.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if subscription is not None:
            if "max_operators" in changes:
                subscription.base_operators = int(changes["max_operators"])
                subscription.extra_operators = 0
            if "price_per_minute_toman" in changes:
                subscription.price_per_minute_toman = int(changes["price_per_minute_toman"])
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=tenant_id,
        action="tenant.update",
        payload=changes,
        ip=client_ip(request),
    )
    return TenantOut.model_validate(tenant)


@router.get("/tenants/{tenant_id}/users")
async def tenant_users(
    tenant_id: UUID,
    staff: StaffDep,
    session: StaffSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    base = select(User).where(User.tenant_id == tenant_id)
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (await session.execute(base.order_by(User.created_at).offset(offset).limit(limit))).scalars().all()
    items = [UserOut.model_validate(row) for row in rows]
    return {"items": items, "total": total, "next_cursor": str(offset + limit) if offset + len(items) < total else None}


@router.post("/tenants/{tenant_id}/suspend", response_model=TenantOut)
async def suspend_tenant(
    tenant_id: UUID, request: Request, staff: SuperAdminDep, session: StaffSession
) -> TenantOut:
    return await _set_tenant_status(tenant_id, "suspended", request, staff, session)


@router.post("/tenants/{tenant_id}/activate", response_model=TenantOut)
async def activate_tenant(
    tenant_id: UUID, request: Request, staff: SuperAdminDep, session: StaffSession
) -> TenantOut:
    return await _set_tenant_status(tenant_id, "active", request, staff, session)


async def _set_tenant_status(
    tenant_id: UUID, new_status: str, request: Request, staff: Any, session: Any
) -> TenantOut:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError("not_found", "tenant not found")
    tenant.status = new_status
    registry_status = (
        await session.execute(
            select(TenantDatabaseRegistry.status).where(
                TenantDatabaseRegistry.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if registry_status == "ready":
        async with session_scope(tenant_id) as tenant_session:
            projection = await tenant_session.get(Tenant, tenant_id, with_for_update=True)
            if projection is not None:
                projection.status = new_status
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        tenant_id=tenant_id,
        action=f"tenant.{new_status}",
        ip=client_ip(request),
    )
    return TenantOut.model_validate(tenant)


@router.post("/tenants/{tenant_id}/topups", status_code=status.HTTP_201_CREATED)
async def create_topup(
    tenant_id: UUID,
    payload: TopupCreate,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, Any]:
    """Staff-applied credit (§10). PSP integration later reuses this ledger kind."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError("not_found", "tenant not found")
    key = payload.idempotency_key or f"topup:{uuid4()}"
    async with session_scope(tenant_id) as tenant_session:
        tenant_projection = await tenant_session.get(Tenant, tenant_id)
        if tenant_projection is None:
            raise ApiError("not_found", "tenant database is not ready")
        entry = await billing.topup(
            tenant_session,
            tenant=tenant_projection,
            minutes=payload.minutes,
            toman=payload.toman,
            idempotency_key=key,
        )
        balance = await billing.get_balance(tenant_session, tenant_id)
        await audit.record(
            tenant_session,
            actor_type="staff",
            actor_id=staff.id,
            tenant_id=tenant_id,
            action="tenant.topup",
            payload={
                "minutes": payload.minutes,
                "toman": entry.toman_delta,
                "note": payload.note,
            },
            ip=client_ip(request),
        )
    return {
        "ledger_entry_id": str(entry.id),
        "balance_seconds": balance.seconds,
        "balance_toman": balance.toman,
    }


@router.get("/jobs")
async def list_jobs(
    staff: StaffDep,
    session: StaffSession,
    job_status: Annotated[str | None, Query(alias="status")] = None,
    kind: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    jobs: list[Job] = []
    total = 0
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            stmt = select(Job).where(Job.tenant_id == tenant_id)
            if job_status:
                stmt = stmt.where(Job.status == job_status)
            if kind:
                stmt = stmt.where(Job.kind == kind)
            total += int((await tenant_session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
            jobs.extend(
                (
                    await tenant_session.execute(
                        stmt.order_by(Job.created_at.desc()).limit(offset + limit)
                    )
                ).scalars()
            )
    jobs.sort(key=lambda row: row.created_at, reverse=True)
    page_rows = jobs[offset : offset + limit]
    return {"items": [JobOut.model_validate(row) for row in page_rows], "total": total, "next_cursor": str(offset + limit) if offset + len(page_rows) < total else None}


@router.get("/operations")
async def operations(
    staff: StaffDep,
    session: StaffSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    pending_outbox: list[JobOutbox] = []
    job_counts: dict[str, int] = {}
    outbox_total = 0
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            outbox_total += int(
                (
                    await tenant_session.execute(
                        select(func.count(JobOutbox.id)).where(
                            JobOutbox.tenant_id == tenant_id,
                            JobOutbox.dispatched_at.is_(None),
                        )
                    )
                ).scalar_one()
            )
            pending_outbox.extend(
                (
                    await tenant_session.execute(
                        select(JobOutbox)
                        .where(
                            JobOutbox.tenant_id == tenant_id,
                            JobOutbox.dispatched_at.is_(None),
                        )
                        .order_by(JobOutbox.available_at, JobOutbox.created_at)
                        .limit(offset + limit)
                    )
                ).scalars()
            )
            for job_status, count in (
                await tenant_session.execute(
                    select(Job.status, func.count(Job.id))
                    .where(Job.tenant_id == tenant_id)
                    .group_by(Job.status)
                )
            ).all():
                job_counts[job_status] = job_counts.get(job_status, 0) + int(count)
    pending_outbox.sort(key=lambda row: (row.available_at, row.created_at))
    pending_outbox = pending_outbox[offset : offset + limit]
    return {
        "job_counts": job_counts,
        "outbox_pending": [
            {
                "id": str(row.id),
                "job_id": str(row.job_id) if row.job_id else None,
                "tenant_id": str(row.tenant_id),
                "queue_name": row.queue_name,
                "function_name": row.function_name,
                "available_at": row.available_at,
                "attempts": row.attempts,
                "last_error": row.last_error,
                "wait_seconds": max(0, int((now - row.created_at).total_seconds())),
            }
            for row in pending_outbox
        ],
        "outbox_total": outbox_total,
    }


@router.post("/jobs/{job_id}/requeue", status_code=status.HTTP_202_ACCEPTED)
async def requeue_job(job_id: UUID, request: Request, staff: StaffDep) -> dict[str, str]:
    """Reset a job and re-enqueue it only after the DB commit (§6 / ingest pattern)."""
    kind: str
    call_id: UUID
    run_id: UUID | None = None

    resolved_tenant_id = await resolve_tenant_for_job(job_id)
    if resolved_tenant_id is None:
        raise ApiError("not_found", "job not found")
    async with session_scope(resolved_tenant_id) as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise ApiError("not_found", "job not found")
        if job.kind not in QUEUE_BY_KIND:
            raise ApiError("invalid_request", f"unknown job kind {job.kind}")

        job.status = "queued"
        job.attempt = 0
        job.run_after = datetime.now(UTC)
        job.queued_at = datetime.now(UTC)
        job.started_at = None
        job.provider_submitted_at = None
        job.completed_at = None
        job.error_code = None
        job.error_detail = None
        call = (
            await session.execute(
                select(Call).where(Call.id == job.call_id, Call.tenant_id == job.tenant_id)
            )
        ).scalar_one_or_none()
        # Always restore a claimable stage; otherwise workers return "skipped" and
        # the Redis message is consumed while the job row stays queued.
        target_status = {
            "asr": "stored",
            "emotion": "emotion_queued",
            "llm": "transcribed",
            "notify": "billed",
        }[job.kind]
        if call is not None:
            call.status = target_status
            call.error_code = None
            restored = progress.values_for_status(call.status)
            if "progress_pct" in restored:
                call.progress_pct = int(restored["progress_pct"])
            call.progress_detail = str(restored["progress_detail"])
            call.updated_at = datetime.now(UTC)

        await audit.record(
            session,
            actor_type="staff",
            actor_id=staff.id,
            tenant_id=job.tenant_id,
            action="job.requeue",
            payload={"job_id": str(job_id), "kind": job.kind, "call_id": str(job.call_id)},
            ip=client_ip(request),
        )

        kind, call_id, tenant_id = job.kind, job.call_id, job.tenant_id
        if kind in {"emotion", "llm"}:
            run_id = await _ensure_analysis_run(session, tenant_id, call_id)
        await processing_events.record(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind=kind,
            status="queued",
            message="کار توسط مدیر دوباره در صف قرار گرفت",
            step_key=f"{job.id}:queued:0",
        )
        outbox_id = await outbox.stage_job(
            session,
            job_id=job.id,
            tenant_id=tenant_id,
            call_id=call_id,
            kind=kind,
            analysis_run_id=run_id,
            event="call.complete" if kind == "notify" else None,
        )

    try:
        await outbox.dispatch_one(outbox_id)
    except Exception:
        logger.exception(
            "immediate admin requeue dispatch failed; durable dispatcher will retry",
            extra={"extra_fields": {"job_id": str(job_id)}},
        )
    return {"status": "queued", "job_id": str(job_id)}


async def _ensure_analysis_run(session: AsyncSession, tenant_id: UUID, call_id: UUID) -> UUID:
    run = (
        await session.execute(
            select(AnalysisRun)
            .where(
                AnalysisRun.call_id == call_id,
                AnalysisRun.tenant_id == tenant_id,
            )
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is not None and run.status in {"pending", "queued", "running"}:
        run.status = "queued"
        return run.id
    models = await effective_models(session)
    new_run = AnalysisRun(
        call_id=call_id,
        tenant_id=tenant_id,
        llm_model=capability_model(models, "analysis"),
        ai_provider=models.get("analysis_provider", "aiservice"),
        decision_provider=models.get("decision_provider", "aiservice"),
        decision_model=capability_model(models, "decision"),
        prompt_version=models["prompt_version"],
        system_prompt=await effective_extract_prompt(session, models["prompt_version"]),
        status="queued",
    )
    session.add(new_run)
    await session.flush()
    return new_run.id


@router.get("/settings")
async def get_platform_settings(staff: StaffDep, session: StaffSession) -> dict[str, object]:
    try:
        return await settings_public_view(session)
    except RuntimeError as exc:
        if "provider secret" not in str(exc) and "PLATFORM_SECRETS_KEY" not in str(exc):
            raise
        raise ApiError("invalid_request", str(exc)) from exc


@router.get("/assistant/knowledge-status")
async def assistant_knowledge_status(
    staff: StaffDep, session: StaffSession
) -> dict[str, object]:
    del staff
    settings = await effective_models(session)
    totals = {"ready": 0, "pending": 0, "failed": 0, "chunks": 0}
    latest_error: str | None = None
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            index_status = case(
                (
                    or_(
                        CallKnowledge.vector_status == "failed",
                        CallKnowledge.graph_status == "failed",
                    ),
                    "failed",
                ),
                (
                    and_(
                        CallKnowledge.vector_status == "ready",
                        CallKnowledge.graph_status == "ready",
                    ),
                    "ready",
                ),
                else_="pending",
            ).label("index_status")
            rows = (
                await tenant_session.execute(
                    select(index_status, func.count(CallKnowledge.call_id)).group_by(
                        index_status
                    )
                )
            ).all()
            for state, count in rows:
                if state in totals:
                    totals[state] += int(count)
            totals["chunks"] += int(
                (
                    await tenant_session.execute(select(func.count(TranscriptChunk.id)))
                ).scalar_one()
            )
            if latest_error is None:
                latest_error = (
                    await tenant_session.execute(
                        select(CallKnowledge.error_detail)
                        .where(CallKnowledge.error_detail.is_not(None))
                        .order_by(CallKnowledge.updated_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
    return {
        "embedding_model": (
            settings["ninerouter_embedding_model"]
            if settings["embedding_provider"] == "ninerouter_direct"
            else settings["embedding_model"]
        ),
        "embedding_route": settings["embedding_provider"],
        "embedding_configured": bool(
            settings["ninerouter_embedding_model"] and settings["ninerouter_api_key"]
            if settings["embedding_provider"] == "ninerouter_direct"
            else settings["embedding_model"] and settings["api_key"]
        ),
        **totals,
        "latest_error": latest_error[:500] if latest_error else None,
    }


@router.post("/assistant/knowledge-retry")
async def retry_assistant_knowledge(
    payload: KnowledgeRetryRequest,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, object]:
    tenant_ids = await operational_tenant_ids()
    if payload.tenant_id is not None:
        if payload.tenant_id not in tenant_ids:
            raise ApiError("not_found", "tenant not found")
        tenant_ids = [payload.tenant_id]
    queued = 0
    for tenant_id in tenant_ids:
        async with session_scope(tenant_id) as tenant_session:
            stmt = select(CallKnowledge.call_id).where(CallKnowledge.tenant_id == tenant_id)
            if payload.call_id is not None:
                stmt = stmt.where(CallKnowledge.call_id == payload.call_id)
            if payload.failed_only:
                stmt = stmt.where(
                    or_(
                        CallKnowledge.vector_status == "failed",
                        CallKnowledge.graph_status == "failed",
                    )
                )
            call_ids = (await tenant_session.execute(stmt.limit(100))).scalars().all()
            for call_id in call_ids:
                await knowledge.index_call(tenant_session, tenant_id, call_id)
                queued += 1
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="assistant.knowledge_retry",
        payload={
            "tenant_id": str(payload.tenant_id) if payload.tenant_id else None,
            "call_id": str(payload.call_id) if payload.call_id else None,
            "processed": queued,
        },
        ip=client_ip(request),
    )
    return {"status": "completed", "processed": queued}


@router.patch("/settings")
async def update_platform_settings(
    payload: SettingsUpdate, request: Request, staff: SuperAdminDep, session: StaffSession
) -> dict[str, object]:
    changes = payload.model_dump(exclude_none=True)
    embedding_configuration_changed = bool(
        {"embedding_provider", "embedding_model", "ninerouter_embedding_model"}
        & changes.keys()
    )
    api_key = changes.pop("api_key", None)
    asr_api_key = changes.pop("asr_api_key", None)
    decision_api_key = changes.pop("decision_api_key", None)
    embedding_api_key = changes.pop("embedding_api_key", None)
    ninerouter_api_key = changes.pop("ninerouter_api_key", None)
    assistant_instructions = changes.pop("assistant_instructions", None)
    optional_blank_keys = {
        "ninerouter_asr_prompt",
        "ninerouter_analysis_prompt",
        "ninerouter_chat_prompt",
        "ninerouter_decision_prompt",
        "ninerouter_asr_model",
        "ninerouter_analysis_model",
        "ninerouter_assistant_model",
        "ninerouter_decision_model",
        "ninerouter_embedding_model",
        "ninerouter_direct_asr_prompt",
        "ninerouter_direct_analysis_prompt",
        "ninerouter_direct_assistant_prompt",
        "ninerouter_direct_correction_prompt",
        "ninerouter_direct_decision_prompt",
    }
    for key, value in changes.items():
        if key in optional_blank_keys:
            continue
        if not str(value).strip():
            raise ApiError("invalid_request", f"{key} must not be empty")
    if api_key is not None:
        stripped = normalize_api_key(str(api_key))
        if stripped:
            base_url = changes.get("voicesanj_base_url")
            if base_url is None:
                saved_url = await session.get(PlatformSetting, "voicesanj_base_url")
                base_url = saved_url.value if saved_url is not None else None
            if base_url is not None:
                await _validate_voicesanj_api_key(stripped, base_url=base_url)
            else:
                await _validate_voicesanj_api_key(stripped)
            changes["api_key"] = stripped
    selected_llm_provider = changes.get("llm_provider")
    if selected_llm_provider == "voicesanj":
        saved_shared_key = await session.get(PlatformSetting, "api_key")
        effective_llm_key = normalize_api_key(
            changes.get("api_key")
            or (saved_shared_key.value if saved_shared_key is not None else None)
        )
        if not effective_llm_key:
            raise ApiError("invalid_request", "LLM API key is required")
    if asr_api_key is not None:
        stripped_asr_key = normalize_api_key(str(asr_api_key))
        if stripped_asr_key:
            changes["asr_api_key"] = stripped_asr_key
    if decision_api_key is not None:
        stripped_decision_key = normalize_api_key(str(decision_api_key))
        if stripped_decision_key:
            changes["decision_api_key"] = stripped_decision_key
    if embedding_api_key is not None:
        stripped_embedding_key = normalize_api_key(str(embedding_api_key))
        if stripped_embedding_key:
            changes["embedding_api_key"] = stripped_embedding_key
    if ninerouter_api_key is not None:
        stripped_ninerouter_key = normalize_api_key(str(ninerouter_api_key))
        if stripped_ninerouter_key:
            try:
                changes["ninerouter_api_key"] = encrypt_secret(stripped_ninerouter_key)
            except RuntimeError as exc:
                raise ApiError("invalid_request", str(exc)) from exc
    direct_provider_keys = {
        "asr_ai_provider": "ninerouter_asr_model",
        "analysis_provider": "ninerouter_analysis_model",
        "assistant_provider": "ninerouter_assistant_model",
        "correction_provider": "ninerouter_correction_models",
        "decision_provider": "ninerouter_decision_model",
        "embedding_provider": "ninerouter_embedding_model",
    }
    for provider_key, model_key in direct_provider_keys.items():
        if not {provider_key, model_key, "ninerouter_api_key"}.intersection(changes):
            continue
        saved_provider = await session.get(PlatformSetting, provider_key)
        provider = changes.get(
            provider_key, saved_provider.value if saved_provider else "aiservice"
        )
        if provider != "ninerouter_direct":
            continue
        saved_secret = await session.get(PlatformSetting, "ninerouter_api_key")
        encrypted = changes.get("ninerouter_api_key") or (
            saved_secret.value if saved_secret else ""
        )
        try:
            if not decrypt_secret(encrypted):
                raise ApiError("invalid_request", "9Router API key is required")
        except RuntimeError as exc:
            raise ApiError("invalid_request", str(exc)) from exc
        selected = changes.get(model_key)
        if selected is None:
            saved_model = await session.get(PlatformSetting, model_key)
            selected = saved_model.value if saved_model else None
        if model_key == "ninerouter_correction_models":
            if isinstance(selected, str):
                try:
                    selected = json.loads(selected)
                except ValueError:
                    selected = []
            valid = (
                isinstance(selected, list)
                and bool(selected)
                and all(str(item).strip() for item in selected)
            )
        else:
            valid = isinstance(selected, str) and bool(selected.strip())
        if not valid:
            raise ApiError("invalid_request", f"{model_key} is required")
    selected_asr_provider = changes.get("asr_provider")
    if selected_asr_provider == "local" and get_settings().asr_engine in {
        "voicesanj",
        "whisper",
    }:
        raise ApiError("invalid_request", "local ASR is not configured on this server")
    if selected_asr_provider in {"voicesanj", "openai_compatible"}:
        saved_asr_key = await session.get(PlatformSetting, "asr_api_key")
        effective_asr_key = normalize_api_key(
            changes.get("asr_api_key")
            or (saved_asr_key.value if saved_asr_key is not None else None)
        )
        if not effective_asr_key and selected_asr_provider == "voicesanj":
            saved_shared_key = await session.get(PlatformSetting, "api_key")
            effective_asr_key = normalize_api_key(
                changes.get("api_key")
                or (saved_shared_key.value if saved_shared_key is not None else None)
            )
        if not effective_asr_key:
            raise ApiError("invalid_request", "ASR API key is required")
    for url_key in ("voicesanj_base_url", "asr_base_url", "embedding_base_url", "ninerouter_base_url"):
        if url_key not in changes:
            continue
        try:
            changes[url_key] = normalize_provider_base_url(changes[url_key])
        except ValueError as exc:
            raise ApiError("invalid_request", str(exc)) from exc
    prompt_version = changes.get("prompt_version")
    if prompt_version is not None and prompt_version not in available_prompt_versions():
        raise ApiError("invalid_request", f"unknown prompt version: {prompt_version}")
    extract_prompt = changes.pop("extract_prompt", None)
    if extract_prompt is not None:
        active_prompt_version = prompt_version
        if active_prompt_version is None:
            active_prompt_version = (await effective_models(session))["prompt_version"]
        if active_prompt_version != "extract-fa-v3":
            raise ApiError("invalid_request", "extract prompt editing requires extract-fa-v3")
        extract_prompt = extract_prompt.strip()
        if not extract_prompt:
            raise ApiError("invalid_request", "extract_prompt must not be empty")
    for key in ("asr_model", "llm_model", "chat_model"):
        if key in changes:
            changes[key] = str(changes[key]).strip()
    ninerouter_prompt_keys = optional_blank_keys
    for key in ninerouter_prompt_keys:
        if key in changes:
            changes[key] = str(changes[key]).strip()
    for key in ("correction_audio_models", "correction_text_models", "ninerouter_correction_models"):
        if key not in changes:
            continue
        normalized = [str(item).strip() for item in changes[key] if str(item).strip()]
        if key == "ninerouter_correction_models" and not normalized:
            changes[key] = []
            continue
        if not normalized or len(normalized) != len(set(normalized)):
            raise ApiError("invalid_request", f"{key} must contain unique model ids")
        changes[key] = normalized
    denoiser_model = changes.get("audio_denoiser_model")
    if denoiser_model is not None and denoiser_model not in DENOISER_MODELS:
        raise ApiError("invalid_request", f"unknown denoiser model: {denoiser_model}")
    enhancement_model = changes.get("audio_enhancement_model")
    if enhancement_model is not None and enhancement_model not in ENHANCEMENT_MODELS:
        raise ApiError("invalid_request", f"unknown enhancement model: {enhancement_model}")
    for key, value in changes.items():
        row = await session.get(PlatformSetting, key)
        if row is None:
            session.add(
                PlatformSetting(
                    key=key,
                    value=(
                        json.dumps(value, ensure_ascii=False)
                        if isinstance(value, list)
                        else str(value)
                    ),
                )
            )
        else:
            row.value = (
                json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value)
            )
            row.updated_at = datetime.now(UTC)
    if extract_prompt is not None:
        row = await session.get(PlatformSetting, EXTRACT_PROMPT_KEY)
        if row is None:
            session.add(PlatformSetting(key=EXTRACT_PROMPT_KEY, value=extract_prompt))
        else:
            row.value = extract_prompt
            row.updated_at = datetime.now(UTC)
    if assistant_instructions is not None:
        row = await session.get(PlatformSetting, "assistant-instructions")
        if row is None:
            session.add(
                PlatformSetting(
                    key="assistant-instructions", value=assistant_instructions.strip()
                )
            )
        else:
            row.value = assistant_instructions.strip()
            row.updated_at = datetime.now(UTC)
    changed_settings = set(changes)
    if extract_prompt is not None:
        changed_settings.add("extract_prompt")
    if assistant_instructions is not None:
        changed_settings.add("assistant_instructions")
    audit_payload: dict[str, Any] = {"changed_settings": sorted(changed_settings)}
    providers = {
        key: value
        for key, value in changes.items()
        if key.endswith("_provider") and key != "llm_provider"
    }
    if providers:
        audit_payload["providers"] = providers
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="settings.update",
        payload=audit_payload,
        ip=client_ip(request),
    )
    await session.flush()
    if embedding_configuration_changed:
        await knowledge.invalidate_embeddings()
    return await settings_public_view(session)


async def _validate_voicesanj_api_key(api_key: str, base_url: str | None = None) -> None:
    """Reject keys that VoiceSanj will not accept before persisting them."""
    if base_url is not None:
        try:
            base_url = normalize_provider_base_url(base_url)
        except ValueError as exc:
            raise ApiError("invalid_request", str(exc)) from exc
    runtime = get_settings().model_copy(
        update={
            "voicesanj_api_key": api_key,
            "voicesanj_base_url": base_url or get_settings().voicesanj_base_url,
        }
    )
    if not (runtime.voicesanj_base_url or "").strip():
        raise ApiError("invalid_request", "VOICESANJ_BASE_URL is not configured")
    try:
        await VoiceSanjClient(runtime).validate_api_key()
    except ProviderError as exc:
        raise ApiError(
            "invalid_request",
            exc.detail,
            retryable=exc.retryable,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - surface probe failure to admin UI
        raise ApiError(
            "invalid_request",
            f"اعتبارسنجی کلید API ناموفق بود: {exc}",
        ) from exc


@router.get("/models", response_model=list[ProviderModelOut])
async def list_provider_models(staff: StaffDep, session: StaffSession) -> list[ProviderModelOut]:
    """Proxy VoiceSanj model catalog for the admin model picker (user API)."""
    runtime = await resolve_provider_settings(session)
    if not (runtime.voicesanj_base_url or "").strip():
        raise ApiError("invalid_request", "VOICESANJ_BASE_URL is not configured")
    if not (runtime.voicesanj_api_key or "").strip():
        raise ApiError(
            "invalid_request",
            "کلید API تنظیم نشده است. ابتدا آن را در تنظیمات مدل ذخیره کنید.",
        )
    try:
        client = VoiceSanjClient(runtime)
        rows = await client.list_models()
    except ProviderError as exc:
        code = "invalid_request" if not exc.retryable else "internal"
        raise ApiError(code, exc.detail, retryable=exc.retryable) from exc
    except Exception as exc:  # noqa: BLE001 - surface provider failure to admin UI
        raise ApiError("internal", f"failed to list models: {exc}") from exc

    out: list[ProviderModelOut] = []
    for item in rows:
        model_id = str(item.get("id") or item.get("model_id") or "").strip()
        if not model_id:
            continue
        kind = str(item.get("kind") or "").strip().lower() or "unknown"
        display = str(item.get("display_name") or model_id).strip()
        available_raw = item.get("available")
        available = available_raw if isinstance(available_raw, bool) else None
        out.append(
            ProviderModelOut(
                id=model_id,
                kind=kind,
                display_name=display,
                description=str(item.get("description") or ""),
                recommended=bool(item.get("recommended")),
                available=available,
                status=str(item["status"]) if item.get("status") is not None else None,
                language=str(item["language"]) if item.get("language") is not None else None,
                model_id=str(item["model_id"]) if item.get("model_id") is not None else None,
                architecture=(
                    str(item["architecture"]) if item.get("architecture") is not None else None
                ),
                license=str(item["license"]) if item.get("license") is not None else None,
            )
        )
    return sorted(
        out,
        key=lambda item: (
            item.kind,
            item.available is False,
            not item.recommended,
            item.display_name.casefold(),
        ),
    )


async def _ninerouter_runtime(
    session: AsyncSession, payload: NineRouterConnectionInput | None = None
) -> Settings:
    updates = payload.model_dump(exclude_none=True) if payload else {}
    # Connection discovery must not depend on models or the other provider's configuration.
    values: dict[str, Any] = {}
    for key in NineRouterConnectionInput.model_fields:
        value = updates.get(key)
        if key == "ninerouter_api_key":
            value = normalize_api_key(value)
        if value is None or (key == "ninerouter_api_key" and not value):
            row = await session.get(PlatformSetting, key)
            if row is not None:
                value = decrypt_secret(row.value) if key == "ninerouter_api_key" else row.value
        if value is not None:
            values[key] = value
    values["ninerouter_base_url"] = normalize_provider_base_url(
        str(values.get("ninerouter_base_url") or "http://127.0.0.1:20128")
    )
    for key in ("ninerouter_connect_timeout_seconds", "ninerouter_read_timeout_seconds"):
        if key in values:
            values[key] = float(values[key])
    return get_settings().model_copy(update=values)


async def _ninerouter_models(
    session: AsyncSession, kind: str, payload: NineRouterConnectionInput | None = None
) -> list[ProviderModelOut]:
    client = None
    try:
        client = NineRouterClient(await _ninerouter_runtime(session, payload))
        rows = await client.list_models(kind)
    except ProviderError as exc:
        raise ApiError(
            "internal" if exc.retryable else "invalid_request", exc.detail, retryable=exc.retryable
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise ApiError("invalid_request", str(exc)) from exc
    finally:
        if client is not None:
            await client.close()
    mapped_kind = "asr" if kind == "stt" else "embedding" if kind == "embedding" else "llm"
    return [
        ProviderModelOut(
            id=str(item["id"]),
            kind=mapped_kind,
            display_name=str(item.get("display_name") or item["id"]),
            description=str(item.get("description") or ""),
            available=True,
            status="ready",
        )
        for item in rows
    ]


@router.get("/ninerouter/models", response_model=list[ProviderModelOut])
async def list_ninerouter_models(
    staff: StaffDep,
    session: StaffSession,
    kind: Annotated[str, Query(pattern="^(chat|stt|embedding)$")] = "chat",
) -> list[ProviderModelOut]:
    return await _ninerouter_models(session, kind)


@router.post("/ninerouter/models", response_model=list[ProviderModelOut])
async def preview_ninerouter_models(
    payload: NineRouterConnectionInput,
    staff: SuperAdminDep,
    session: StaffSession,
    kind: Annotated[str, Query(pattern="^(chat|stt|embedding)$")] = "chat",
) -> list[ProviderModelOut]:
    return await _ninerouter_models(session, kind, payload)


@router.post("/ninerouter/test")
async def test_ninerouter_connection(
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
    payload: NineRouterConnectionInput | None = None,
) -> dict[str, Any]:
    client = None
    try:
        client = NineRouterClient(await _ninerouter_runtime(session, payload))
        health = await client.health()
        chat_models = await client.list_models("chat")
    except ProviderError as exc:
        await audit.record(
            session,
            actor_type="staff",
            actor_id=staff.id,
            action="ninerouter.connection_test",
            payload={"provider": "ninerouter_direct", "status": "failed"},
            ip=client_ip(request),
        )
        await session.commit()
        raise ApiError(
            "internal" if exc.retryable else "invalid_request", exc.detail, retryable=exc.retryable
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise ApiError("invalid_request", str(exc)) from exc
    finally:
        if client is not None:
            await client.close()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="ninerouter.connection_test",
        payload={"provider": "ninerouter_direct", "status": "connected"},
        ip=client_ip(request),
    )
    return {
        "status": "connected",
        "version": health.get("version"),
        "chat_models": len(chat_models),
    }


@router.post("/settings/test-correction")
async def test_correction_path(staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    runtime = await resolve_provider_settings(session, capability="correction")
    stages: list[dict[str, str]] = []
    source = [
        {
            "id": "connection-test-1",
            "channel": 0,
            "t_start_ms": 0,
            "t_end_ms": 1500,
            "text": "سلام وقت بخیر شماره سفارش ۱۲۳ است.",
        }
    ]
    revision = SimpleNamespace(
        text_models=runtime.correction_text_models,
        idempotency_key=f"admin-correction-test-{uuid4()}",
    )
    client = CorrectionClient(runtime)
    current_stage = "submit"
    try:
        if runtime.active_ai_provider == "ninerouter_direct":
            model = runtime.correction_text_models[0]
            result = await client.complete_direct(
                source,
                runtime.correction_prompt,
                model=model,
            )
            stages.append({"stage": "provider", "status": "succeeded"})
            validate_result(
                source,
                result,
                max_uncertain_ratio=runtime.correction_max_uncertain_ratio,
            )
            stages.append({"stage": "validation", "status": "succeeded"})
            return {"status": "succeeded", "model": model, "stages": stages}
        task_id = await client.submit(
            revision,
            source,
            runtime.correction_prompt,
            model=runtime.correction_text_models[0],
        )
        stages.append({"stage": "submit", "status": "succeeded"})
        current_stage = "provider"
        deadline = asyncio.get_running_loop().time() + 30
        while True:
            task = await client.status(task_id)
            task_status = str(task.get("status") or "unknown")
            if task_status in {"succeeded", "partially_succeeded"}:
                stages.append({"stage": "provider", "status": task_status})
                result = await client.result(task_id)
                current_stage = "validation"
                validate_result(
                    source,
                    result,
                    max_uncertain_ratio=runtime.correction_max_uncertain_ratio,
                )
                stages.append({"stage": "validation", "status": "succeeded"})
                return {"status": "succeeded", "task_id": task_id, "stages": stages}
            if task_status in {"failed", "cancelled"}:
                stages.append({"stage": "provider", "status": task_status})
                raise ApiError(
                    "invalid_request",
                    str(task.get("error") or task.get("error_code") or task_status),
                )
            if asyncio.get_running_loop().time() >= deadline:
                stages.append({"stage": "provider", "status": task_status})
                return {"status": "running", "task_id": task_id, "stages": stages}
            await asyncio.sleep(1)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ApiError(
            "invalid_request",
            f"آزمایش مسیر تصحیح در مرحله {current_stage} ناموفق بود: {exc}",
        ) from exc
    finally:
        await client.close()


@router.get("/packages")
async def admin_list_packages(
    staff: StaffDep,
    session: StaffSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    total = int((await session.execute(select(func.count(Package.id)))).scalar_one())
    rows = (await session.execute(select(Package).order_by(Package.minutes).offset(offset).limit(limit))).scalars().all()
    return {"items": [PackageOut.model_validate(row) for row in rows], "total": total, "next_cursor": str(offset + limit) if offset + len(rows) < total else None}


@router.post("/packages", response_model=PackageOut, status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: PackageCreate, request: Request, staff: SuperAdminDep, session: StaffSession
) -> PackageOut:
    package = Package(
        name=payload.name,
        minutes=payload.minutes,
        price_toman=payload.price_toman,
        active=payload.active,
    )
    session.add(package)
    await session.flush()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="package.create",
        payload={"package_id": str(package.id), "name": payload.name},
        ip=client_ip(request),
    )
    return PackageOut.model_validate(package)


@router.delete("/packages/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_package(
    package_id: UUID, request: Request, staff: SuperAdminDep, session: StaffSession
) -> None:
    package = await session.get(Package, package_id)
    if package is None:
        raise ApiError("not_found", "package not found")
    package.active = False
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="package.deactivate",
        payload={"package_id": str(package_id)},
        ip=client_ip(request),
    )


@router.patch("/packages/{package_id}", response_model=PackageOut)
async def update_package(
    package_id: UUID,
    payload: PackageUpdate,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> PackageOut:
    package = await session.get(Package, package_id, with_for_update=True)
    if package is None:
        raise ApiError("not_found", "package not found")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(package, field, value)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="package.update",
        payload={"package_id": str(package_id), "changes": changes},
        ip=client_ip(request),
    )
    return PackageOut.model_validate(package)


@router.get("/audit")
async def list_audit_events(
    staff: StaffDep,
    session: StaffSession,
    tenant_id: Annotated[UUID | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    stmt = select(AuditEvent)
    if tenant_id:
        stmt = stmt.where(AuditEvent.tenant_id == tenant_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (await session.execute(stmt.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit))).scalars().all()
    return {"items": [AuditEventOut.model_validate(row) for row in rows], "total": total, "next_cursor": str(offset + limit) if offset + len(rows) < total else None}


@router.get("/tenants/{tenant_id}/ledger")
async def tenant_ledger(
    tenant_id: UUID,
    staff: StaffDep,
    session: StaffSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    total = int((await session.execute(select(func.count(LedgerEntry.id)).where(LedgerEntry.tenant_id == tenant_id))).scalar_one())
    rows = (
        await session.execute(
            select(LedgerEntry)
            .where(LedgerEntry.tenant_id == tenant_id)
            .order_by(LedgerEntry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    items = [
        {
            "id": str(row.id),
            "kind": row.kind,
            "seconds_delta": row.seconds_delta,
            "toman_delta": row.toman_delta,
            "call_id": str(row.call_id) if row.call_id else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    return {"items": items, "total": total, "next_cursor": str(offset + limit) if offset + len(items) < total else None}


@router.get("/tenants/{tenant_id}/transcripts/count")
async def tenant_transcript_count(
    tenant_id: UUID, staff: StaffDep, session: StaffSession
) -> dict[str, int]:
    total = int(
        (
            await session.execute(
                select(func.count(Transcript.call_id)).where(Transcript.tenant_id == tenant_id)
            )
        ).scalar_one()
    )
    return {"transcripts": total}


@router.get("/staff")
async def list_staff(
    staff: StaffDep,
    session: StaffSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    total = int((await session.execute(select(func.count(StaffUser.id)))).scalar_one())
    rows = (await session.execute(select(StaffUser).order_by(StaffUser.created_at).offset(offset).limit(limit))).scalars().all()
    items = [
        {
            "id": str(row.id),
            "email": row.email,
            "role": row.role,
            "two_factor_enabled": bool(row.totp_secret),
            "disabled_at": row.disabled_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    return {"items": items, "total": total, "next_cursor": str(offset + limit) if offset + len(items) < total else None}


@router.post("/staff", status_code=status.HTTP_201_CREATED)
async def create_staff(
    payload: StaffCreate,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, Any]:
    await _verify_sensitive_staff_action(
        session, staff, payload.current_password, payload.totp_code
    )
    email = str(payload.email).strip().lower()
    if (await session.execute(select(StaffUser.id).where(StaffUser.email == email))).scalar_one_or_none():
        raise ApiError("conflict_idempotency", "staff email already exists")
    row = StaffUser(email=email, password_hash=hash_password(payload.password), role=payload.role)
    session.add(row)
    await session.flush()
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="staff.create", payload={"staff_id": str(row.id), "email": email, "role": row.role}, ip=client_ip(request))
    return {"id": str(row.id), "email": row.email, "role": row.role, "disabled_at": None}


@router.post("/staff/{staff_id}/disable")
async def disable_staff(
    staff_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, Any]:
    await _verify_sensitive_staff_action(session, staff, payload.current_password, payload.totp_code)
    if staff_id == staff.id:
        raise ApiError("invalid_request", "you cannot disable your own account")
    row = await session.get(StaffUser, staff_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "staff user not found")
    row.disabled_at = datetime.now(UTC)
    await session.execute(update(StaffRefreshToken).where(StaffRefreshToken.staff_user_id == row.id, StaffRefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="staff.disable", payload={"staff_id": str(row.id)}, ip=client_ip(request))
    return {"id": str(row.id), "disabled_at": row.disabled_at}


@router.post("/staff/{staff_id}/activate")
async def activate_staff(
    staff_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, Any]:
    await _verify_sensitive_staff_action(session, staff, payload.current_password, payload.totp_code)
    row = await session.get(StaffUser, staff_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "staff user not found")
    row.disabled_at = None
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="staff.activate", payload={"staff_id": str(row.id)}, ip=client_ip(request))
    return {"id": str(row.id), "disabled_at": None}


@router.post("/staff/{staff_id}/reset-password")
async def reset_staff_password(
    staff_id: UUID,
    payload: StaffPasswordReset,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, str]:
    await _verify_sensitive_staff_action(session, staff, payload.current_password, payload.totp_code)
    row = await session.get(StaffUser, staff_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "staff user not found")
    row.password_hash = hash_password(payload.password)
    await session.execute(update(StaffRefreshToken).where(StaffRefreshToken.staff_user_id == row.id, StaffRefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="staff.password_reset", payload={"staff_id": str(row.id)}, ip=client_ip(request))
    return {"status": "updated"}


@router.post("/staff/{staff_id}/reset-totp")
async def reset_staff_totp(
    staff_id: UUID,
    payload: StaffSensitiveAction,
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, str]:
    await _verify_sensitive_staff_action(session, staff, payload.current_password, payload.totp_code)
    row = await session.get(StaffUser, staff_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "staff user not found")
    row.totp_secret = None
    row.totp_pending_secret = None
    await session.execute(update(StaffRefreshToken).where(StaffRefreshToken.staff_user_id == row.id, StaffRefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="staff.totp_reset", payload={"staff_id": str(row.id)}, ip=client_ip(request))
    return {"status": "reset"}
