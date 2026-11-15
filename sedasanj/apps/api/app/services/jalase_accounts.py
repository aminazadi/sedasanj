"""Personal Jalase-Negar accounts: one single-user tenant per mobile number."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ApiKey, Tenant, User
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
