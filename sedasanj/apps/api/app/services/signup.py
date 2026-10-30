from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Subscription, Tenant, TenantBalanceCache, TrialClaim, User
from app.security import hash_password
from app.services import audit, commerce, plan_credit
from app.services.commerce_settings import get_commerce_settings
from app.services.phone_identity import mobile_lock


async def create_account(
    session: AsyncSession,
    *,
    mobile: str,
    email: str,
    organization_name: str,
    manager_name: str,
    password: str,
    plan_code: str,
    ip: str | None,
) -> tuple[Tenant, User]:
    """Create one organization and its initial subscription in the caller's transaction."""
    await mobile_lock(session, mobile)
    existing = (
        await session.execute(select(User.id).where(func.lower(User.email) == email).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError("conflict_idempotency", "این ایمیل قبلاً ثبت شده است.")
    is_demo = plan_code == "demo"
    if is_demo:
        used = (
            await session.execute(
                select(TrialClaim.id)
                .where(
                    (func.lower(TrialClaim.email) == email) | (TrialClaim.mobile == mobile),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if used is not None:
            raise ApiError("conflict_idempotency", "دموی این شماره قبلاً فعال شده است.")
    _, version = await commerce.plan_version_by_code(session, plan_code)
    trial_days = version.trial_days or 0
    if is_demo and not trial_days:
        raise ApiError("plan_not_sellable", "مدت دوره آزمایشی این پلن تنظیم نشده است.")
    now = datetime.now(UTC)
    payment_window = timedelta(days=(await get_commerce_settings(session)).payment_window_days)
    tenant = Tenant(
        name=organization_name.strip(),
        status="active",
        timezone="Asia/Tehran",
        locale="fa",
        price_per_minute_toman=version.overage_price_per_minute_toman,
        max_concurrent_jobs=10,
        audio_retention_days=30,
        max_operators=version.base_operators,
    )
    session.add(tenant)
    await session.flush()
    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password(password),
        role="org_admin",
        mobile_number=mobile,
        display_name=manager_name.strip(),
    )
    session.add(user)
    session.add(TenantBalanceCache(tenant_id=tenant.id, seconds=0, toman=0))
    subscription = Subscription(
        tenant_id=tenant.id,
        plan_version_id=version.id,
        status="trialing" if is_demo else "pending_payment",
        billing_period="trial" if is_demo else "annual",
        period_start=now,
        # An unpaid sign-up lapses after the payment window; payment starts the real term.
        period_end=now + timedelta(days=trial_days) if is_demo else now + payment_window,
        base_operators=version.base_operators,
        extra_operators=0,
        price_per_minute_toman=version.overage_price_per_minute_toman,
        assistant_tier=version.assistant_tier,
        assistant_monthly_messages=version.assistant_monthly_messages,
        assistant_source_limit=version.assistant_source_limit,
        assistant_model=version.assistant_model,
    )
    session.add(subscription)
    await session.flush()
    if is_demo:
        session.add(TrialClaim(tenant_id=tenant.id, email=email, mobile=mobile))
        await plan_credit.ensure_period_credit(
            session,
            tenant.id,
            subscription_id=subscription.id,
            subscription_start=subscription.period_start,
            subscription_end=subscription.period_end,
            minutes=version.intro_minutes,
            now=now,
        )
        subscription.intro_credit_issued_at = now
    await audit.record(
        session,
        actor_type="user",
        actor_id=user.id,
        tenant_id=tenant.id,
        action="signup.complete",
        payload={"plan": plan_code},
        ip=ip,
    )
    return tenant, user
