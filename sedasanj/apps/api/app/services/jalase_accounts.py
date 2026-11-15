"""Personal Jalase-Negar accounts: one single-user tenant per mobile number."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ApiKey, Plan, PlanVersion, Subscription, Tenant, User
from app.security import generate_api_key
from app.services import audit
from app.services.api_scopes import MOBILE_KEY_SCOPES
from app.services.signup import create_account

PRODUCT = "jalase_negar"
CHANNEL = "jalase_app"
FREE_PLAN_CODE = "jn_free"
DEFAULT_NAME = "کاربر جلسه‌نگار"


def mask_mobile(mobile: str) -> str:
    """`09123456789` -> `0912***6789`; the full number never goes into names or logs."""
    return f"{mobile[:4]}***{mobile[-4:]}" if len(mobile) >= 8 else "***"


async def create_personal_account(
    session: AsyncSession, *, mobile: str, display_name: str | None, ip: str | None
) -> tuple[Tenant, User]:
    """Create the personal tenant, its only user and the free-plan subscription."""
    name = (display_name or "").strip() or DEFAULT_NAME
    return await create_account(
        session,
        mobile=mobile,
        email=f"jn-{uuid4().hex}@accounts.sedasanj.ir",
        organization_name=f"{name} ({mask_mobile(mobile)})",
        manager_name=name,
        password=secrets.token_urlsafe(48),
        plan_code=FREE_PLAN_CODE,
        ip=ip,
        product=PRODUCT,
        signup_channel=CHANNEL,
    )


async def issue_device_key(
    session: AsyncSession,
    *,
    user: User,
    device_name: str,
    platform: str,
    app_version: str | None,
    ip: str | None,
) -> tuple[str, str, ApiKey]:
    """Create a personal mobile token; the secret is returned exactly once."""
    limit = get_settings().meeting_token_limit
    active_keys = list(
        (
            await session.execute(
                select(ApiKey)
                .where(
                    ApiKey.user_id == user.id,
                    ApiKey.kind == "mobile",
                    ApiKey.revoked_at.is_(None),
                )
                .order_by(func.coalesce(ApiKey.last_used_at, ApiKey.created_at))
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    # A personal account has no panel to revoke devices from, so the least recently used
    # device is signed out instead of refusing the new login.
    for stale in active_keys[: max(0, len(active_keys) - limit + 1)]:
        stale.revoked_at = datetime.now(UTC)
    secret, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        tenant_id=user.tenant_id,
        user_id=user.id,
        kind="mobile",
        key_hash=key_hash,
        key_prefix=prefix,
        label=device_name.strip()[:120],
        archive_format="gzip",
        scopes=list(MOBILE_KEY_SCOPES),
    )
    session.add(api_key)
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=user.id,
        tenant_id=user.tenant_id,
        action="jalase.device.login",
        payload={"api_key_id": str(api_key.id), "platform": platform, "app_version": app_version},
        ip=ip,
    )
    return secret, prefix, api_key


async def restore_free_plan(session: AsyncSession, tenant_id: UUID, now: datetime) -> bool:
    """Put a personal account whose paid month lapsed back on the permanent free plan.

    A Jalase-Negar account never ends up without a plan: it keeps its documents and gets the
    free monthly allowance again, with an upgrade prompt in the app.  Returns True when the
    subscription was reset.
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or tenant.product != PRODUCT:
        return False
    live = (
        await session.execute(
            select(Subscription.id)
            .where(Subscription.tenant_id == tenant_id, Subscription.status == "active")
            .limit(1)
        )
    ).first()
    if live is not None:
        return False
    row = (
        await session.execute(
            select(Subscription)
            .where(Subscription.tenant_id == tenant_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    free = (
        await session.execute(
            select(PlanVersion)
            .join(Plan, Plan.id == PlanVersion.plan_id)
            .where(Plan.code == FREE_PLAN_CODE, PlanVersion.status == "published")
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or free is None:
        return False
    row.plan_version_id = free.id
    row.status = "active"
    row.billing_period = "monthly"
    row.period_start = now
    row.period_end = datetime(9999, 12, 31, tzinfo=UTC)
    row.cancel_at_period_end = False
    row.next_plan_version_id = None
    row.llm_monthly_tokens = free.llm_monthly_tokens
    row.updated_at = now
    await audit.record(
        session,
        actor_type="system",
        tenant_id=tenant_id,
        action="jalase.plan_lapsed_to_free",
        payload={"subscription_id": str(row.id)},
    )
    return True
