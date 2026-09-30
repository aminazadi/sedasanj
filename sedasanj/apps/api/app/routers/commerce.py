from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, or_, select

from app.config import get_settings
from app.db import routable_tenant_ids, session_scope
from app.deps import OrgAdminDep, PublicSession, StaffDep, StaffSession, TenantSession, client_ip
from app.errors import ApiError
from app.models import (
    AssistantUsage,
    AuditEvent,
    ContactLead,
    CreditGrant,
    CreditReservation,
    InstallationRequest,
    Invoice,
    LedgerEntry,
    Order,
    OrderItem,
    Package,
    PaymentAttempt,
    Plan,
    PlanVersion,
    Refund,
    SignupOtp,
    Subscription,
    SubscriptionChange,
    Tenant,
    TenantBalanceCache,
    TenantDatabaseRegistry,
    TrialClaim,
    User,
)
from app.security import hash_password
from app.services import audit, commerce, entitlements, payments, ratelimit
from app.services.commerce_settings import (
    get_commerce_settings,
    update_commerce_settings,
)
from app.services.commerce_settings import (
    public_view as commerce_settings_public_view,
)

router = APIRouter(prefix="/v1", tags=["commerce"])


class ContactLeadCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    organization: str = Field(min_length=2, max_length=200)
    mobile: str = Field(min_length=10, max_length=15)
    email: EmailStr
    message: str = Field(min_length=10, max_length=3000)
    source: str = Field(default="contact_page", max_length=64)
    website: str = Field(default="", max_length=200)


class OtpRequest(BaseModel):
    mobile: str
    email: EmailStr


class OtpVerify(BaseModel):
    otp_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class SignupComplete(BaseModel):
    otp_id: UUID
    organization_name: str = Field(min_length=2, max_length=200)
    manager_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    mobile: str
    password: str = Field(min_length=8, max_length=128)
    plan_code: str = Field(pattern=r"^(demo|bronze|silver|gold)$")


class CheckoutCreate(BaseModel):
    plan_code: str = Field(pattern=r"^(bronze|silver|gold)$")
    billing_period: Literal["monthly", "annual"]
    extra_operators: int = Field(default=0, ge=0, le=500)
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: EmailStr
    customer_mobile: str
    invoice_profile: dict[str, Any] = Field(default_factory=dict)
    terms_accepted: bool


class CreditOrderCreate(BaseModel):
    minutes: int | None = Field(default=None, ge=10, le=1_000_000)
    package_id: UUID | None = None


class SubscriptionChangeCreate(BaseModel):
    plan_code: str = Field(pattern=r"^(bronze|silver|gold)$")
    extra_operators: int = Field(default=0, ge=0, le=500)


class InstallationCreate(BaseModel):
    kind: Literal["initial", "reinstall", "dedicated"]
    pbx_type: str = Field(min_length=2, max_length=120)
    pbx_version: str | None = Field(default=None, max_length=120)
    extension_count: int = Field(ge=1, le=100_000)
    connection_method: str = Field(min_length=2, max_length=200)
    technical_contact: str = Field(min_length=2, max_length=200)
    preferred_time: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=3000)


class LeadUpdate(BaseModel):
    status: Literal["new", "contacted", "qualified", "closed"] | None = None
    internal_notes: str | None = Field(default=None, max_length=3000)
    follow_up_at: datetime | None = None


class InstallationUpdate(BaseModel):
    status: Literal["requested", "paid", "reviewing", "scheduled", "in_progress", "completed", "canceled"] | None = None
    internal_notes: str | None = Field(default=None, max_length=3000)
    scheduled_at: datetime | None = None


class PlanVersionCreate(BaseModel):
    monthly_price_toman: int = Field(ge=0)
    annual_price_toman: int | None = Field(default=None, ge=0)
    base_operators: int = Field(ge=0)
    intro_minutes: int = Field(ge=0)
    overage_price_per_minute_toman: int = Field(default=2000, ge=0)
    assistant_tier: str = Field(min_length=2, max_length=32)
    assistant_monthly_messages: int = Field(ge=0)
    assistant_source_limit: int = Field(ge=1, le=200)
    assistant_model: str | None = None
    allows_extra_operators: bool = False
    extra_operator_monthly_toman: int | None = Field(default=None, ge=0)
    extra_operator_annual_toman: int | None = Field(default=None, ge=0)
    trial_days: int | None = Field(default=None, ge=1, le=90)

    @model_validator(mode="after")
    def validate_pricing(self) -> PlanVersionCreate:
        if self.allows_extra_operators:
            if self.extra_operator_monthly_toman is None:
                raise ValueError("monthly extra-operator price is required")
            if self.annual_price_toman is not None and self.extra_operator_annual_toman is None:
                raise ValueError("annual extra-operator price is required")
        elif self.extra_operator_monthly_toman is not None or self.extra_operator_annual_toman is not None:
            raise ValueError("extra-operator prices require allows_extra_operators")
        return self


class PlanCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_]{2,32}$")
    name: str = Field(min_length=2, max_length=120)
    public: bool = True
    sort_order: int = Field(default=0, ge=0, le=10000)


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    active: bool | None = None
    public: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class PlanPublish(BaseModel):
    effective_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class ReasonAction(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class SubscriptionAdminAction(ReasonAction):
    action: Literal["cancel_at_period_end", "resume", "stop_now", "extend", "extend_trial"]
    days: int | None = Field(default=None, ge=1, le=3660)


class RefundCreate(ReasonAction):
    amount_toman: int = Field(gt=0)
    method: Literal["reverse", "manual"]
    payment_attempt_id: UUID | None = None
    external_reference: str | None = Field(default=None, max_length=128)


class CommerceSettingsUpdate(BaseModel):
    gateway_enabled: bool | None = None
    zarinpal_merchant_id: str | None = Field(default=None, min_length=36, max_length=64)
    zarinpal_sandbox: bool | None = None
    custom_credit_price_per_minute_toman: int | None = Field(default=None, ge=0)
    installation_initial_toman: int | None = Field(default=None, ge=0)
    installation_reinstall_toman: int | None = Field(default=None, ge=0)
    installation_dedicated_toman: int | None = Field(default=None, ge=0)
    renewal_lead_days: int | None = Field(default=None, ge=1, le=60)
    terms_version: str | None = Field(default=None, min_length=1, max_length=32)
    terms_url: str | None = Field(default=None, max_length=500)
    tax_percent: int | None = Field(default=None, ge=0, le=100)
    automatic_discounts_enabled: bool | None = None


def _mobile(value: str) -> str:
    normalized = value.strip().replace(" ", "").replace("-", "")
    if normalized.startswith("+98"):
        normalized = "0" + normalized[3:]
    if not re.fullmatch(r"09\d{9}", normalized):
        raise ApiError("invalid_request", "mobile number is invalid")
    return normalized


def _plan_out(plan: Plan, version: PlanVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "plan_id": str(plan.id),
        "code": plan.code,
        "name": plan.name,
        "version": version.version,
        "status": version.status,
        "effective_at": version.effective_at,
        "published_at": version.published_at,
        "retired_at": version.retired_at,
        "monthly_price_toman": version.monthly_price_toman,
        "annual_price_toman": version.annual_price_toman,
        "base_operators": version.base_operators,
        "intro_minutes": version.intro_minutes,
        "overage_price_per_minute_toman": version.overage_price_per_minute_toman,
        "assistant_tier": version.assistant_tier,
        "assistant_monthly_messages": version.assistant_monthly_messages,
        "assistant_source_limit": version.assistant_source_limit,
        "assistant_model": version.assistant_model,
        "allows_extra_operators": version.allows_extra_operators,
        "extra_operator_monthly_toman": version.extra_operator_monthly_toman,
        "extra_operator_annual_toman": version.extra_operator_annual_toman,
        "trial_days": version.trial_days,
    }


@router.get("/plans")
async def list_plans(session: PublicSession) -> list[dict[str, Any]]:
    return [_plan_out(plan, version) for plan, version in await commerce.public_plans(session)]


@router.post("/contact-leads", status_code=status.HTTP_201_CREATED)
async def create_contact_lead(payload: ContactLeadCreate, request: Request, session: PublicSession) -> dict[str, str]:
    if payload.website:
        return {"status": "accepted"}
    ip = client_ip(request) or "unknown"
    await ratelimit.enforce(f"contact:{ip}", 5, 3600)
    lead = ContactLead(name=payload.name.strip(), organization=payload.organization.strip(), mobile=_mobile(payload.mobile), email=str(payload.email).lower(), message=payload.message.strip(), source=payload.source)
    session.add(lead)
    await session.flush()
    await audit.record(session, actor_type="public", action="contact_lead.created", payload={"lead_id": str(lead.id), "source": lead.source}, ip=ip)
    return {"status": "accepted"}


async def _send_otp(mobile: str, code: str) -> None:
    settings = get_settings()
    if not settings.smsir_api_key or not settings.smsir_verify_template_id:
        if settings.environment == "production":
            raise ApiError("internal", "SMS provider is not configured")
        return
    headers = {"X-API-KEY": settings.smsir_api_key, "Content-Type": "application/json"}
    body = {"mobile": mobile, "templateId": settings.smsir_verify_template_id, "parameters": [{"name": "CODE", "value": code}]}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{settings.smsir_base_url.rstrip('/')}/send/verify", headers=headers, json=body)
    if not response.is_success:
        raise ApiError("internal", "SMS provider rejected the verification request", retryable=True)


@router.post("/signup/otp/request", status_code=status.HTTP_201_CREATED)
async def request_signup_otp(payload: OtpRequest, request: Request, session: PublicSession) -> dict[str, Any]:
    mobile = _mobile(payload.mobile)
    email = str(payload.email).strip().lower()
    ip = client_ip(request) or "unknown"
    await ratelimit.enforce(f"signup-otp-ip:{ip}", 10, 3600)
    await ratelimit.enforce(f"signup-otp-mobile:{mobile}", 5, 3600)
    recent = (await session.execute(select(SignupOtp).where(SignupOtp.mobile == mobile).order_by(SignupOtp.created_at.desc()).limit(1))).scalar_one_or_none()
    now = datetime.now(UTC)
    if recent and recent.created_at > now - timedelta(seconds=60):
        raise ApiError("rate_limited", "wait before requesting another code")
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = SignupOtp(mobile=mobile, email=email, code_hash=hash_password(code), expires_at=now + timedelta(minutes=2))
    session.add(row)
    await session.flush()
    await _send_otp(mobile, code)
    await audit.record(session, actor_type="public", action="signup.otp_requested", payload={"otp_id": str(row.id)}, ip=ip)
    result: dict[str, Any] = {"otp_id": str(row.id), "expires_in": 120}
    if get_settings().environment != "production" and not get_settings().smsir_api_key:
        result["development_code"] = code
    return result


@router.post("/signup/otp/verify")
async def verify_signup_otp(payload: OtpVerify, request: Request, session: PublicSession) -> dict[str, bool]:
    from app.security import verify_password

    row = await session.get(SignupOtp, payload.otp_id, with_for_update=True)
    if row is None or row.expires_at <= datetime.now(UTC) or row.attempts >= 5:
        raise ApiError("unauthorized", "verification code is not usable")
    row.attempts += 1
    if not verify_password(row.code_hash, payload.code):
        await audit.record(session, actor_type="public", action="signup.otp_failed", payload={"otp_id": str(row.id), "attempt": row.attempts}, ip=client_ip(request))
        raise ApiError("unauthorized", "verification code is invalid")
    row.verified_at = datetime.now(UTC)
    await audit.record(session, actor_type="public", action="signup.otp_verified", payload={"otp_id": str(row.id)}, ip=client_ip(request))
    return {"verified": True}


@router.post("/signup/complete", status_code=status.HTTP_201_CREATED)
async def complete_signup(payload: SignupComplete, request: Request, session: PublicSession) -> dict[str, Any]:
    mobile = _mobile(payload.mobile)
    email = str(payload.email).strip().lower()
    otp = await session.get(SignupOtp, payload.otp_id, with_for_update=True)
    if otp is None or otp.verified_at is None or otp.expires_at <= datetime.now(UTC) or otp.mobile != mobile or str(otp.email).lower() != email:
        raise ApiError("unauthorized", "verified signup session is required")
    if (await session.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none() is not None:
        raise ApiError("conflict_idempotency", "email is already registered")
    if payload.plan_code == "demo":
        used = (await session.execute(select(TrialClaim).where((func.lower(TrialClaim.email) == email) | (TrialClaim.mobile == mobile)))).scalar_one_or_none()
        if used is not None:
            raise ApiError("conflict_idempotency", "demo has already been used")
    _, version = await commerce.plan_version_by_code(session, payload.plan_code)
    now = datetime.now(UTC)
    is_demo = payload.plan_code == "demo"
    tenant = Tenant(name=payload.organization_name.strip(), status="active", timezone="Asia/Tehran", locale="fa", price_per_minute_toman=version.overage_price_per_minute_toman, monthly_minute_quota=None, max_concurrent_jobs=10, audio_retention_days=30, max_operators=version.base_operators)
    session.add(tenant)
    await session.flush()
    user = User(tenant_id=tenant.id, email=email, password_hash=hash_password(payload.password), role="org_admin", mobile_number=mobile, display_name=payload.manager_name.strip())
    session.add(user)
    session.add(TenantBalanceCache(tenant_id=tenant.id, seconds=0, toman=0))
    subscription = Subscription(tenant_id=tenant.id, plan_version_id=version.id, status="trialing" if is_demo else "pending_payment", billing_period="trial" if is_demo else "monthly", period_start=now, period_end=now + timedelta(days=version.trial_days or 7) if is_demo else commerce.add_months(now, 1), base_operators=version.base_operators, extra_operators=0, price_per_minute_toman=version.overage_price_per_minute_toman, assistant_tier=version.assistant_tier, assistant_monthly_messages=version.assistant_monthly_messages, assistant_source_limit=version.assistant_source_limit, assistant_model=version.assistant_model)
    session.add(subscription)
    await session.flush()
    if is_demo:
        session.add(TrialClaim(tenant_id=tenant.id, email=email, mobile=mobile))
        await payments.grant_credit(session, tenant_id=tenant.id, seconds=version.intro_minutes * 60, source="intro_bonus", source_id=subscription.id, expires_at=subscription.period_end, toman=0, idem=f"trial:{subscription.id}")
        subscription.intro_credit_issued_at = now
    await audit.record(session, actor_type="user", actor_id=user.id, tenant_id=tenant.id, action="signup.complete", payload={"plan": payload.plan_code}, ip=client_ip(request))
    return {"tenant_id": str(tenant.id), "requires_payment": not is_demo, "plan_code": payload.plan_code}


@router.post("/checkout/quote")
async def checkout_quote(payload: CheckoutCreate, principal: OrgAdminDep, session: TenantSession) -> dict[str, int]:
    _, version = await commerce.plan_version_by_code(session, payload.plan_code)
    total, extra_unit = commerce.subscription_amount(version, payload.billing_period, payload.extra_operators)
    return {"base_toman": total - extra_unit * payload.extra_operators, "extra_operators_toman": extra_unit * payload.extra_operators, "total_toman": total}


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(payload: CheckoutCreate, request: Request, principal: OrgAdminDep, session: TenantSession, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    if not payload.terms_accepted:
        raise ApiError("invalid_request", "terms must be accepted")
    assert principal.tenant_id is not None
    tenant = await session.get(Tenant, principal.tenant_id)
    assert tenant is not None
    order = await commerce.create_subscription_order(session, tenant=tenant, plan_code=payload.plan_code, period=payload.billing_period, extra_operators=payload.extra_operators, customer_name=payload.customer_name, customer_email=str(payload.customer_email), customer_mobile=_mobile(payload.customer_mobile), invoice_profile=payload.invoice_profile, idempotency_key=idempotency_key)
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="order.created", payload={"order_id": str(order.id), "kind": order.kind, "amount_toman": order.amount_toman}, ip=client_ip(request))
    return {"id": str(order.id), "number": order.number, "amount_toman": order.amount_toman, "status": order.status}


@router.post("/orders/{order_id}/pay")
async def pay_order(order_id: UUID, request: Request, principal: OrgAdminDep, session: TenantSession) -> dict[str, str]:
    assert principal.tenant_id is not None
    order = (await session.execute(select(Order).where(Order.id == order_id, Order.tenant_id == principal.tenant_id).with_for_update())).scalar_one_or_none()
    if order is None:
        raise ApiError("not_found", "order not found")
    attempt, url = await payments.initiate(session, order)
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="payment.initiated", payload={"order_id": str(order.id), "payment_id": str(attempt.id)}, ip=client_ip(request))
    return {"payment_id": str(attempt.id), "redirect_url": url}


@router.get("/payments/zarinpal/callback", include_in_schema=False)
async def zarinpal_callback(
    session: PublicSession,
    token: str,
    Authority: str = Query(alias="Authority"),
    Status: str = Query(alias="Status"),
) -> RedirectResponse:
    ready_tenants = list(
        (
            await session.execute(
                select(TenantDatabaseRegistry.tenant_id).where(
                    TenantDatabaseRegistry.status == "ready"
                )
            )
        ).scalars()
    )
    legacy_statement = select(Order.id).where(Order.callback_token == token)
    if ready_tenants:
        legacy_statement = legacy_statement.where(Order.tenant_id.not_in(ready_tenants))
    legacy_order = (await session.execute(legacy_statement)).scalar_one_or_none()
    if legacy_order is not None:
        order = await payments.verify_callback(
            session, token=token, authority=Authority, status=Status
        )
    else:
        order = None
        for tenant_id in ready_tenants:
            async with session_scope(tenant_id) as tenant_session:
                candidate = (
                    await tenant_session.execute(
                        select(Order.id).where(Order.callback_token == token)
                    )
                ).scalar_one_or_none()
                if candidate is not None:
                    order = await payments.verify_callback(
                        tenant_session,
                        token=token,
                        authority=Authority,
                        status=Status,
                    )
                    break
        if order is None:
            raise ApiError("not_found", "order not found")
    assert order is not None
    return RedirectResponse(f"{get_settings().public_app_url.rstrip('/')}/payment-result?order={order.id}&status={order.status}", status_code=303)


@router.get("/subscription")
async def get_subscription(principal: OrgAdminDep, session: TenantSession) -> dict[str, Any]:
    assert principal.tenant_id is not None
    value = await entitlements.effective(session, principal.tenant_id)
    row = None
    plan = None
    version = None
    if value.subscription_id:
        result = (
            await session.execute(
                select(Subscription, Plan, PlanVersion)
                .join(PlanVersion, PlanVersion.id == Subscription.plan_version_id)
                .join(Plan, Plan.id == PlanVersion.plan_id)
                .where(Subscription.id == value.subscription_id)
            )
        ).one_or_none()
        if result:
            row, plan, version = result
    used = 0
    if value.period_start:
        used = int((await session.execute(select(func.count(AssistantUsage.id)).where(AssistantUsage.tenant_id == principal.tenant_id, AssistantUsage.period_start >= value.period_start, AssistantUsage.status == "succeeded"))).scalar_one())
    return {"id": str(value.subscription_id) if value.subscription_id else None, "status": value.status, "plan_code": plan.code if plan else None, "plan_name": plan.name if plan else None, "plan_version": version.version if version else None, "billing_period": row.billing_period if row else None, "cancel_at_period_end": row.cancel_at_period_end if row else False, "next_plan_version_id": str(row.next_plan_version_id) if row and row.next_plan_version_id else None, "base_operators": row.base_operators if row else 0, "extra_operators": row.extra_operators if row else 0, "max_operators": value.max_operators, "price_per_minute_toman": value.price_per_minute_toman, "assistant_tier": value.assistant_tier, "assistant_monthly_messages": value.assistant_monthly_messages, "assistant_messages_used": used, "assistant_messages_remaining": max(0, value.assistant_monthly_messages - used), "assistant_source_limit": value.assistant_source_limit, "assistant_model": value.assistant_model, "period_start": value.period_start, "period_end": value.period_end}


@router.post("/subscription/cancel-at-period-end")
async def cancel_subscription(request: Request, principal: OrgAdminDep, session: TenantSession) -> dict[str, bool]:
    assert principal.tenant_id is not None
    row = (await session.execute(select(Subscription).where(Subscription.tenant_id == principal.tenant_id, Subscription.status.in_(("active", "trialing"))).order_by(Subscription.created_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "active subscription not found")
    row.cancel_at_period_end = True
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="subscription.cancel_scheduled", payload={"subscription_id": str(row.id)}, ip=client_ip(request))
    return {"cancel_at_period_end": True}


@router.post("/subscription/resume")
async def resume_subscription(request: Request, principal: OrgAdminDep, session: TenantSession) -> dict[str, bool]:
    assert principal.tenant_id is not None
    row = (await session.execute(select(Subscription).where(Subscription.tenant_id == principal.tenant_id, Subscription.status == "active").order_by(Subscription.created_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "active subscription not found")
    row.cancel_at_period_end = False
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="subscription.resumed", payload={"subscription_id": str(row.id)}, ip=client_ip(request))
    return {"cancel_at_period_end": False}


@router.post("/subscription/change")
async def change_subscription(payload: SubscriptionChangeCreate, request: Request, principal: OrgAdminDep, session: TenantSession, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    assert principal.tenant_id is not None
    current = (await session.execute(select(Subscription).where(Subscription.tenant_id == principal.tenant_id, Subscription.status == "active").order_by(Subscription.created_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
    if current is None:
        raise ApiError("not_found", "active subscription not found")
    _, target = await commerce.plan_version_by_code(session, payload.plan_code)
    operator_count = int((await session.execute(select(func.count(User.id)).where(User.tenant_id == principal.tenant_id, User.role == "operator"))).scalar_one())
    if operator_count > target.base_operators + payload.extra_operators:
        raise ApiError("quota_exceeded", "active operators exceed the target plan capacity")
    current_version = await session.get(PlanVersion, current.plan_version_id)
    if current_version is None:
        raise ApiError("internal", "current plan version is missing")
    period = "annual" if current.billing_period == "annual" else "monthly"
    current_total, _ = commerce.subscription_amount(current_version, period, current.extra_operators)
    target_total, _ = commerce.subscription_amount(target, period, payload.extra_operators)
    if target_total <= current_total:
        current.next_plan_version_id = target.id
        session.add(SubscriptionChange(tenant_id=principal.tenant_id, subscription_id=current.id, kind="downgrade", status="scheduled", target_plan_version_id=target.id, requested_extra_operators=payload.extra_operators, effective_at=current.period_end))
        await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="subscription.change_scheduled", payload={"subscription_id": str(current.id), "target_plan_version_id": str(target.id), "extra_operators": payload.extra_operators}, ip=client_ip(request))
        return {"status": "scheduled", "effective_at": current.period_end}
    existing = (await session.execute(select(Order).where(Order.tenant_id == principal.tenant_id, Order.idempotency_key == idempotency_key))).scalar_one_or_none()
    if existing is not None:
        return {"status": existing.status, "order_id": str(existing.id), "amount_toman": existing.amount_toman}
    amount = commerce.prorated_amount(target_total - current_total, current.period_start, current.period_end, datetime.now(UTC))
    admin = await session.get(User, principal.id)
    assert admin is not None
    order = Order(tenant_id=principal.tenant_id, number=f"UP-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(4).upper()}", kind="subscription_upgrade", status="draft", amount_toman=amount, callback_token=secrets.token_urlsafe(32), idempotency_key=idempotency_key, customer_name=admin.display_name or admin.email, customer_email=admin.email, customer_mobile=admin.mobile_number or "", invoice_profile={})
    session.add(order)
    await session.flush()
    session.add(OrderItem(order_id=order.id, tenant_id=principal.tenant_id, kind="subscription_upgrade", description="ارتقای اشتراک", quantity=1, unit_price_toman=amount, total_toman=amount, metadata_json={"subscription_id": str(current.id), "target_plan_version_id": str(target.id), "extra_operators": payload.extra_operators}))
    session.add(SubscriptionChange(tenant_id=principal.tenant_id, subscription_id=current.id, kind="upgrade", status="pending_payment", target_plan_version_id=target.id, requested_extra_operators=payload.extra_operators, effective_at=datetime.now(UTC), order_id=order.id))
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="subscription.upgrade_requested", payload={"subscription_id": str(current.id), "order_id": str(order.id), "target_plan_version_id": str(target.id)}, ip=client_ip(request))
    return {"status": "payment_required", "order_id": str(order.id), "amount_toman": amount}


@router.get("/orders")
async def list_orders(
    principal: OrgAdminDep,
    session: TenantSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    assert principal.tenant_id is not None
    total = int((await session.execute(select(func.count(Order.id)).where(Order.tenant_id == principal.tenant_id))).scalar_one())
    rows = (await session.execute(select(Order, Invoice.id).outerjoin(Invoice, Invoice.order_id == Order.id).where(Order.tenant_id == principal.tenant_id).order_by(Order.created_at.desc()).offset(offset).limit(limit))).all()
    items = [{"id": str(row.id), "number": row.number, "kind": row.kind, "status": row.status, "amount_toman": row.amount_toman, "created_at": row.created_at, "paid_at": row.paid_at, "invoice_id": str(invoice_id) if invoice_id else None} for row, invoice_id in rows]
    return _page(items, total, offset, limit)


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: UUID, principal: OrgAdminDep, session: TenantSession) -> dict[str, Any]:
    assert principal.tenant_id is not None
    row = (await session.execute(select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == principal.tenant_id))).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "invoice not found")
    return {"id": str(row.id), "number": row.number, "amount_toman": row.amount_toman, "profile": row.profile_snapshot, "issued_at": row.issued_at}


@router.get("/billing/credit-packages")
async def credit_packages(session: PublicSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Package).where(Package.active.is_(True)).order_by(Package.minutes))).scalars().all()
    return [{"id": str(row.id), "name": row.name, "minutes": row.minutes, "price_toman": row.price_toman} for row in rows]


@router.post("/billing/credit-orders", status_code=status.HTTP_201_CREATED)
async def create_credit_order(payload: CreditOrderCreate, request: Request, principal: OrgAdminDep, session: TenantSession, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    assert principal.tenant_id is not None
    if bool(payload.minutes) == bool(payload.package_id):
        raise ApiError("invalid_request", "select a package or enter custom minutes")
    minutes: int
    amount: int
    if payload.package_id:
        package = await session.get(Package, payload.package_id)
        if package is None or not package.active:
            raise ApiError("not_found", "credit package not found")
        minutes, amount = package.minutes, package.price_toman
    else:
        minutes = int(payload.minutes or 0)
        commerce_config = await get_commerce_settings(session)
        amount = minutes * commerce_config.custom_credit_price_per_minute_toman
    admin = await session.get(User, principal.id)
    assert admin is not None
    existing = (await session.execute(select(Order).where(Order.tenant_id == principal.tenant_id, Order.idempotency_key == idempotency_key))).scalar_one_or_none()
    if existing:
        return {"id": str(existing.id), "amount_toman": existing.amount_toman}
    order = Order(tenant_id=principal.tenant_id, number=f"CR-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(4).upper()}", kind="credit", status="draft", amount_toman=amount, callback_token=secrets.token_urlsafe(32), idempotency_key=idempotency_key, customer_name=admin.display_name or admin.email, customer_email=admin.email, customer_mobile=admin.mobile_number or "", invoice_profile={})
    session.add(order)
    await session.flush()
    unit_price = amount // minutes if minutes else 0
    session.add(OrderItem(order_id=order.id, tenant_id=principal.tenant_id, kind="credit", description=f"{minutes} دقیقه اعتبار تحلیل", quantity=minutes, unit_price_toman=unit_price, total_toman=amount, metadata_json={}))
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="credit_order.created", payload={"order_id": str(order.id), "minutes": minutes, "amount_toman": amount}, ip=client_ip(request))
    return {"id": str(order.id), "amount_toman": amount}


@router.get("/installation-requests")
async def list_installations(
    principal: OrgAdminDep,
    session: TenantSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    assert principal.tenant_id is not None
    total = int((await session.execute(select(func.count(InstallationRequest.id)).where(InstallationRequest.tenant_id == principal.tenant_id))).scalar_one())
    rows = (await session.execute(select(InstallationRequest).where(InstallationRequest.tenant_id == principal.tenant_id).order_by(InstallationRequest.created_at.desc()).offset(offset).limit(limit))).scalars().all()
    items = [{"id": str(row.id), "kind": row.kind, "status": row.status, "pbx_type": row.pbx_type, "extension_count": row.extension_count, "scheduled_at": row.scheduled_at, "created_at": row.created_at, "order_id": str(row.order_id) if row.order_id else None} for row in rows]
    return _page(items, total, offset, limit)


@router.post("/installation-requests", status_code=status.HTTP_201_CREATED)
async def create_installation(payload: InstallationCreate, request: Request, principal: OrgAdminDep, session: TenantSession, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    assert principal.tenant_id is not None
    if payload.kind != "initial":
        existing_order = (
            await session.execute(
                select(Order).where(
                    Order.tenant_id == principal.tenant_id,
                    Order.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing_order is not None:
            existing_request = (
                await session.execute(
                    select(InstallationRequest).where(
                        InstallationRequest.order_id == existing_order.id
                    )
                )
            ).scalar_one_or_none()
            if existing_request is not None:
                return {
                    "id": str(existing_request.id),
                    "status": existing_request.status,
                    "order_id": str(existing_order.id),
                    "amount_toman": existing_order.amount_toman,
                }
    if payload.kind == "initial":
        previous = (await session.execute(select(InstallationRequest).where(InstallationRequest.tenant_id == principal.tenant_id, InstallationRequest.kind == "initial"))).scalar_one_or_none()
        if previous:
            raise ApiError("conflict_idempotency", "initial installation has already been requested")
    commerce_config = await get_commerce_settings(session)
    amount = {
        "initial": commerce_config.installation_initial_toman,
        "reinstall": commerce_config.installation_reinstall_toman,
        "dedicated": commerce_config.installation_dedicated_toman,
    }[payload.kind]
    order: Order | None = None
    if amount:
        admin = await session.get(User, principal.id)
        assert admin is not None
        order = Order(tenant_id=principal.tenant_id, number=f"IN-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(4).upper()}", kind="installation", status="draft", amount_toman=amount, callback_token=secrets.token_urlsafe(32), idempotency_key=idempotency_key, customer_name=admin.display_name or admin.email, customer_email=admin.email, customer_mobile=admin.mobile_number or "", invoice_profile={})
        session.add(order)
        await session.flush()
        session.add(OrderItem(order_id=order.id, tenant_id=principal.tenant_id, kind="installation", description="نصب اختصاصی" if payload.kind == "dedicated" else "نصب مجدد عادی", quantity=1, unit_price_toman=amount, total_toman=amount, metadata_json={"installation_kind": payload.kind}))
    row = InstallationRequest(
        tenant_id=principal.tenant_id,
        order_id=order.id if order else None,
        kind=payload.kind,
        # Keep the installation state machine limited to its documented
        # states.  The linked order is the source of truth before payment.
        status="requested",
        pbx_type=payload.pbx_type,
        pbx_version=payload.pbx_version,
        extension_count=payload.extension_count,
        connection_method=payload.connection_method,
        technical_contact=payload.technical_contact,
        preferred_time=payload.preferred_time,
        notes=payload.notes,
    )
    session.add(row)
    await session.flush()
    await audit.record(session, actor_type="user", actor_id=principal.id, tenant_id=principal.tenant_id, action="installation.created", payload={"installation_id": str(row.id), "order_id": str(order.id) if order else None, "kind": row.kind}, ip=client_ip(request))
    return {"id": str(row.id), "status": row.status, "order_id": str(order.id) if order else None, "amount_toman": amount}


def _page(items: list[dict[str, Any]], total: int, offset: int, limit: int) -> dict[str, Any]:
    next_cursor = str(offset + limit) if offset + len(items) < total else None
    return {"items": items, "next_cursor": next_cursor, "total": total}


async def _locate_tenant_record(model: Any, record_id: UUID) -> UUID:
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            found = (
                await tenant_session.execute(
                    select(model.id).where(
                        model.id == record_id,
                        model.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if found is not None:
                return tenant_id
    raise ApiError("not_found", "record not found")


@router.get("/admin/commerce/overview")
async def admin_commerce_overview(staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    revenue_month = 0
    pending_orders = 0
    payment_attention = 0
    subscription_counts: dict[str, int] = {}
    renewals_due = 0
    refunds_total = 0
    installations_open = 0
    tenants_with_subscription: set[UUID] = set()
    tenant_ids = await routable_tenant_ids()
    for tenant_id in tenant_ids:
        async with session_scope(tenant_id) as tenant_session:
            revenue_month += int((await tenant_session.execute(select(func.coalesce(func.sum(Order.amount_toman), 0)).where(Order.tenant_id == tenant_id, Order.status.in_(("paid", "partially_refunded", "refunded")), Order.paid_at >= month_start))).scalar_one())
            pending_orders += int((await tenant_session.execute(select(func.count(Order.id)).where(Order.tenant_id == tenant_id, Order.status.in_(("draft", "pending_payment"))))).scalar_one())
            payment_attention += int((await tenant_session.execute(select(func.count(PaymentAttempt.id)).where(PaymentAttempt.tenant_id == tenant_id, PaymentAttempt.status == "pending_verification"))).scalar_one())
            for subscription_status, count in (await tenant_session.execute(select(Subscription.status, func.count(Subscription.id)).where(Subscription.tenant_id == tenant_id).group_by(Subscription.status))).all():
                subscription_counts[subscription_status] = subscription_counts.get(subscription_status, 0) + int(count)
                tenants_with_subscription.add(tenant_id)
            renewals_due += int((await tenant_session.execute(select(func.count(Subscription.id)).where(Subscription.tenant_id == tenant_id, Subscription.status == "active", Subscription.period_end <= now + timedelta(days=7), Subscription.period_end > now))).scalar_one())
            refunds_total += int((await tenant_session.execute(select(func.coalesce(func.sum(Refund.amount_toman), 0)).where(Refund.tenant_id == tenant_id, Refund.status == "completed"))).scalar_one())
            installations_open += int((await tenant_session.execute(select(func.count(InstallationRequest.id)).where(InstallationRequest.tenant_id == tenant_id, InstallationRequest.status.not_in(("completed", "canceled"))))).scalar_one())
    leads_new = int((await session.execute(select(func.count(ContactLead.id)).where(ContactLead.status == "new"))).scalar_one())
    missing_subscriptions = len(set(tenant_ids) - tenants_with_subscription)
    return {"revenue_month_toman": revenue_month, "pending_orders": pending_orders, "payments_need_attention": payment_attention, "subscriptions": subscription_counts, "renewals_due": renewals_due, "refunds_total_toman": refunds_total, "new_leads": leads_new, "open_installations": installations_open, "missing_subscriptions": missing_subscriptions}


@router.get("/admin/commerce/leads")
async def admin_leads(staff: StaffDep, session: StaffSession, q: str | None = None, lead_status: str | None = Query(default=None, alias="status"), cursor: int = 0, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    stmt = select(ContactLead)
    if lead_status:
        stmt = stmt.where(ContactLead.status == lead_status)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(ContactLead.name.ilike(term), ContactLead.organization.ilike(term), ContactLead.mobile.ilike(term), ContactLead.email.ilike(term)))
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (await session.execute(stmt.order_by(ContactLead.created_at.desc()).offset(cursor).limit(limit))).scalars().all()
    return _page([{"id": str(row.id), "name": row.name, "organization": row.organization, "mobile": row.mobile, "email": row.email, "message": row.message, "source": row.source, "status": row.status, "owner_id": str(row.owner_id) if row.owner_id else None, "internal_notes": row.internal_notes, "follow_up_at": row.follow_up_at, "created_at": row.created_at} for row in rows], total, cursor, limit)


@router.patch("/admin/commerce/leads/{lead_id}")
async def update_admin_lead(lead_id: UUID, payload: LeadUpdate, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    row = await session.get(ContactLead, lead_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "contact lead not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(row, field, value)
    row.owner_id = staff.id
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="contact_lead.update", payload={"lead_id": str(row.id), "changes": {key: str(value) if isinstance(value, datetime) else value for key, value in changes.items()}}, ip=client_ip(request))
    return {"id": str(row.id), "status": row.status}


@router.get("/admin/commerce/plans")
async def admin_plans(
    staff: StaffDep,
    session: StaffSession,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    stmt = select(Plan, PlanVersion).join(PlanVersion, PlanVersion.plan_id == Plan.id)
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (await session.execute(stmt.order_by(Plan.sort_order, PlanVersion.version.desc()).offset(cursor).limit(limit))).all()
    counts: dict[UUID, int] = {}
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            for version_id, count in (
                await tenant_session.execute(
                    select(Subscription.plan_version_id, func.count(Subscription.id))
                    .where(Subscription.tenant_id == tenant_id)
                    .group_by(Subscription.plan_version_id)
                )
            ).all():
                counts[version_id] = counts.get(version_id, 0) + int(count)
    items = [{"active": plan.active, "public": plan.public, "sort_order": plan.sort_order, "subscription_count": int(counts.get(version.id, 0)), **_plan_out(plan, version)} for plan, version in rows]
    return _page(items, total, cursor, limit)


@router.post("/admin/commerce/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(payload: PlanCreate, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    if (await session.execute(select(Plan.id).where(Plan.code == payload.code))).scalar_one_or_none() is not None:
        raise ApiError("conflict_idempotency", "plan code already exists")
    row = Plan(**payload.model_dump(), active=True)
    session.add(row)
    await session.flush()
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="plan.created", payload={"plan_id": str(row.id), "code": row.code}, ip=client_ip(request))
    return {"id": str(row.id), "code": row.code, "name": row.name, "active": row.active, "public": row.public, "sort_order": row.sort_order}


@router.patch("/admin/commerce/plans/{plan_code}")
async def update_plan(plan_code: str, payload: PlanUpdate, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    row = (await session.execute(select(Plan).where(Plan.code == plan_code).with_for_update())).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "plan not found")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(row, field, value)
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="plan.update", payload={"plan": plan_code, "changes": changes}, ip=client_ip(request))
    return {"id": str(row.id), "code": row.code, "name": row.name, "active": row.active, "public": row.public, "sort_order": row.sort_order}


@router.post("/admin/commerce/plans/{plan_code}/versions", status_code=status.HTTP_201_CREATED)
async def create_plan_version(plan_code: str, payload: PlanVersionCreate, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    plan = (await session.execute(select(Plan).where(Plan.code == plan_code).with_for_update())).scalar_one_or_none()
    if plan is None:
        raise ApiError("not_found", "plan not found")
    next_version = int((await session.execute(select(func.coalesce(func.max(PlanVersion.version), 0)).where(PlanVersion.plan_id == plan.id))).scalar_one()) + 1
    row = PlanVersion(plan_id=plan.id, version=next_version, status="draft", created_by=staff.id, **payload.model_dump())
    session.add(row)
    await session.flush()
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="plan_version.created", payload={"plan": plan.code, "version": next_version}, ip=client_ip(request))
    return _plan_out(plan, row)


@router.post("/admin/commerce/plan-versions/{version_id}/publish")
async def publish_plan_version(version_id: UUID, payload: PlanPublish, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    version = await session.get(PlanVersion, version_id, with_for_update=True)
    if version is None:
        raise ApiError("not_found", "plan version not found")
    if version.status != "draft":
        raise ApiError("invalid_request", "only draft versions can be published")
    now = datetime.now(UTC)
    version.status = "published"
    version.published_at = now
    version.effective_at = payload.effective_at or now
    plan = await session.get(Plan, version.plan_id)
    assert plan is not None
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="plan_version.published", payload={"plan": plan.code, "version": version.version, "effective_at": version.effective_at.isoformat(), "reason": payload.reason}, ip=client_ip(request))
    return _plan_out(plan, version)


@router.post("/admin/commerce/plan-versions/{version_id}/retire")
async def retire_plan_version(version_id: UUID, payload: ReasonAction, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    version = await session.get(PlanVersion, version_id, with_for_update=True)
    if version is None:
        raise ApiError("not_found", "plan version not found")
    if version.status == "retired":
        return {"id": str(version.id), "status": version.status}
    version.status = "retired"
    version.retired_at = datetime.now(UTC)
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="plan_version.retired", payload={"version_id": str(version.id), "reason": payload.reason}, ip=client_ip(request))
    return {"id": str(version.id), "status": version.status}


@router.get("/admin/commerce/subscriptions")
async def admin_subscriptions(staff: StaffDep, session: StaffSession, q: str | None = None, subscription_status: str | None = Query(default=None, alias="status"), cursor: int = 0, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    tenant_names: dict[UUID, str] = {
        tenant_id: name
        for tenant_id, name in (
            await session.execute(select(Tenant.id, Tenant.name))
        ).all()
    }
    normalized_query = q.strip().lower() if q else None
    items: list[dict[str, Any]] = []
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            stmt = (
                select(Subscription, Plan, PlanVersion)
                .join(PlanVersion, PlanVersion.id == Subscription.plan_version_id)
                .join(Plan, Plan.id == PlanVersion.plan_id)
                .where(Subscription.tenant_id == tenant_id)
            )
            if subscription_status:
                stmt = stmt.where(Subscription.status == subscription_status)
            rows = (await tenant_session.execute(stmt)).all()
            for sub, plan, version in rows:
                tenant_name = tenant_names.get(tenant_id, "")
                if normalized_query and normalized_query not in (
                    f"{tenant_name} {plan.name}".lower()
                ):
                    continue
                items.append({"id": str(sub.id), "tenant_id": str(sub.tenant_id), "tenant_name": tenant_name, "plan_code": plan.code, "plan_name": plan.name, "plan_version": version.version, "status": sub.status, "billing_period": sub.billing_period, "period_start": sub.period_start, "period_end": sub.period_end, "cancel_at_period_end": sub.cancel_at_period_end, "base_operators": sub.base_operators, "extra_operators": sub.extra_operators, "assistant_monthly_messages": sub.assistant_monthly_messages, "next_plan_version_id": str(sub.next_plan_version_id) if sub.next_plan_version_id else None, "created_at": sub.created_at})
    items.sort(key=lambda item: item["created_at"], reverse=True)
    total = len(items)
    for item in items:
        item.pop("created_at", None)
    return _page(items[cursor : cursor + limit], total, cursor, limit)


@router.get("/admin/commerce/tenants/{tenant_id}")
async def admin_tenant_commerce(tenant_id: UUID, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError("not_found", "tenant not found")
    async with session_scope(tenant_id) as tenant_session:
        subscriptions = (await tenant_session.execute(select(Subscription).where(Subscription.tenant_id == tenant_id).order_by(Subscription.created_at.desc()))).scalars().all()
        orders = (await tenant_session.execute(select(Order).where(Order.tenant_id == tenant_id).order_by(Order.created_at.desc()).limit(100))).scalars().all()
        grants = (await tenant_session.execute(select(CreditGrant).where(CreditGrant.tenant_id == tenant_id).order_by(CreditGrant.created_at.desc()))).scalars().all()
        reservations = (await tenant_session.execute(select(CreditReservation).where(CreditReservation.tenant_id == tenant_id).order_by(CreditReservation.created_at.desc()).limit(100))).scalars().all()
        ledger = (await tenant_session.execute(select(LedgerEntry).where(LedgerEntry.tenant_id == tenant_id).order_by(LedgerEntry.created_at.desc()).limit(100))).scalars().all()
        audit_rows = (await tenant_session.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.created_at.desc()).limit(100))).scalars().all()
        assistant_used = int((await tenant_session.execute(select(func.count(AssistantUsage.id)).where(AssistantUsage.tenant_id == tenant_id, AssistantUsage.status == "succeeded"))).scalar_one())
    return {
        "subscriptions": [{"id": str(row.id), "plan_version_id": str(row.plan_version_id), "status": row.status, "billing_period": row.billing_period, "period_start": row.period_start, "period_end": row.period_end, "cancel_at_period_end": row.cancel_at_period_end, "base_operators": row.base_operators, "extra_operators": row.extra_operators, "price_per_minute_toman": row.price_per_minute_toman, "assistant_monthly_messages": row.assistant_monthly_messages} for row in subscriptions],
        "orders": [_order_summary(row) for row in orders],
        "credit_grants": [{"id": str(row.id), "source": row.source, "source_id": str(row.source_id) if row.source_id else None, "total_seconds": row.total_seconds, "remaining_seconds": row.remaining_seconds, "expires_at": row.expires_at, "created_at": row.created_at} for row in grants],
        "reservations": [{"id": str(row.id), "call_id": str(row.call_id), "seconds": row.seconds, "status": row.status, "created_at": row.created_at} for row in reservations],
        "ledger": [{"id": str(row.id), "kind": row.kind, "seconds_delta": row.seconds_delta, "toman_delta": row.toman_delta, "created_at": row.created_at} for row in ledger],
        "assistant_messages_total": assistant_used,
        "audit": [{"id": str(row.id), "actor_type": row.actor_type, "actor_id": str(row.actor_id) if row.actor_id else None, "action": row.action, "payload": row.payload, "created_at": row.created_at} for row in audit_rows],
    }


@router.post("/admin/commerce/subscriptions/{subscription_id}/actions")
async def admin_subscription_action(subscription_id: UUID, payload: SubscriptionAdminAction, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    tenant_id = await _locate_tenant_record(Subscription, subscription_id)
    async with session_scope(tenant_id) as tenant_session:
        row = await tenant_session.get(Subscription, subscription_id, with_for_update=True)
        if row is None:
            raise ApiError("not_found", "subscription not found")
        now = datetime.now(UTC)
        if payload.action == "cancel_at_period_end":
            if row.status not in {"active", "trialing"}:
                raise ApiError("invalid_request", "only live subscriptions can be canceled")
            row.cancel_at_period_end = True
        elif payload.action == "resume":
            if row.status != "active":
                raise ApiError("invalid_request", "only active subscriptions can be resumed")
            row.cancel_at_period_end = False
        elif payload.action == "stop_now":
            if row.status not in {"active", "trialing"}:
                raise ApiError("invalid_request", "subscription is not live")
            row.status = "canceled"
            row.period_end = now
        elif payload.action == "extend":
            if not payload.days:
                raise ApiError("invalid_request", "days are required")
            if row.status not in {"active", "expired"}:
                raise ApiError("invalid_request", "subscription cannot be extended")
            row.period_end = max(row.period_end, now) + timedelta(days=payload.days)
            row.status = "active"
        elif payload.action == "extend_trial":
            if not payload.days:
                raise ApiError("invalid_request", "days are required")
            if row.status != "trialing":
                raise ApiError("invalid_request", "only trial subscriptions can extend a trial")
            row.period_end += timedelta(days=payload.days)
        row.updated_at = now
        await audit.record(tenant_session, actor_type="staff", actor_id=staff.id, tenant_id=row.tenant_id, action=f"subscription.{payload.action}", payload={"subscription_id": str(row.id), "days": payload.days, "reason": payload.reason}, ip=client_ip(request))
        return {"id": str(row.id), "status": row.status, "period_end": row.period_end, "cancel_at_period_end": row.cancel_at_period_end}


def _order_summary(row: Order, tenant_name: str | None = None) -> dict[str, Any]:
    return {"id": str(row.id), "tenant_id": str(row.tenant_id), "tenant_name": tenant_name, "number": row.number, "kind": row.kind, "status": row.status, "amount_toman": row.amount_toman, "customer_name": row.customer_name, "customer_mobile": row.customer_mobile, "created_at": row.created_at, "paid_at": row.paid_at}


@router.get("/admin/commerce/orders")
async def admin_orders(staff: StaffDep, session: StaffSession, q: str | None = None, order_status: str | None = Query(default=None, alias="status"), cursor: int = 0, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    tenant_names: dict[UUID, str] = {
        tenant_id: name
        for tenant_id, name in (
            await session.execute(select(Tenant.id, Tenant.name))
        ).all()
    }
    items: list[dict[str, Any]] = []
    normalized_query = q.strip().lower() if q else None
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            stmt = select(Order).where(Order.tenant_id == tenant_id)
            if order_status:
                stmt = stmt.where(Order.status == order_status)
            rows = (await tenant_session.execute(stmt)).scalars().all()
            for order in rows:
                item = _order_summary(order, tenant_names.get(tenant_id))
                if normalized_query and normalized_query not in " ".join(
                    str(value or "").lower()
                    for value in (order.number, order.customer_mobile, item["tenant_name"])
                ):
                    continue
                items.append(item)
    items.sort(key=lambda item: item["created_at"], reverse=True)
    total = len(items)
    return _page(items[cursor : cursor + limit], total, cursor, limit)


@router.get("/admin/commerce/orders/{order_id}")
async def admin_order_detail(order_id: UUID, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    tenant_id = await _locate_tenant_record(Order, order_id)
    async with session_scope(tenant_id) as tenant_session:
        order = await tenant_session.get(Order, order_id)
        if order is None:
            raise ApiError("not_found", "order not found")
        items = (await tenant_session.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
        attempts = (await tenant_session.execute(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id).order_by(PaymentAttempt.created_at.desc()))).scalars().all()
        invoice = (await tenant_session.execute(select(Invoice).where(Invoice.order_id == order.id))).scalar_one_or_none()
        refunds = (await tenant_session.execute(select(Refund).where(Refund.order_id == order.id).order_by(Refund.created_at.desc()))).scalars().all()
    return {**_order_summary(order), "customer_email": order.customer_email, "invoice_profile": order.invoice_profile, "terms_version": order.terms_version, "items": [{"id": str(item.id), "kind": item.kind, "description": item.description, "quantity": item.quantity, "unit_price_toman": item.unit_price_toman, "total_toman": item.total_toman, "metadata": item.metadata_json} for item in items], "payments": [{"id": str(item.id), "status": item.status, "gateway": item.gateway, "amount_rial": item.amount_rial, "authority_hint": f"…{item.authority[-8:]}" if item.authority else None, "ref_id": item.ref_id, "created_at": item.created_at, "verified_at": item.verified_at} for item in attempts], "invoice": {"id": str(invoice.id), "number": invoice.number, "amount_toman": invoice.amount_toman, "profile": invoice.profile_snapshot, "issued_at": invoice.issued_at} if invoice else None, "refunds": [{"id": str(item.id), "amount_toman": item.amount_toman, "status": item.status, "method": item.method, "reason": item.reason, "gateway_reference": item.gateway_reference, "created_at": item.created_at} for item in refunds]}


@router.post("/admin/commerce/orders/{order_id}/cancel")
async def cancel_admin_order(order_id: UUID, payload: ReasonAction, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    tenant_id = await _locate_tenant_record(Order, order_id)
    async with session_scope(tenant_id) as tenant_session:
        order = await tenant_session.get(Order, order_id, with_for_update=True)
        if order is None:
            raise ApiError("not_found", "order not found")
        if order.status not in {"draft", "pending_payment"}:
            raise ApiError("invalid_request", "paid or fulfilled orders cannot be canceled")
        order.status = "canceled"
        await audit.record(tenant_session, actor_type="staff", actor_id=staff.id, tenant_id=order.tenant_id, action="order.canceled", payload={"order_id": str(order.id), "reason": payload.reason}, ip=client_ip(request))
        return {"id": str(order.id), "status": order.status}


@router.get("/admin/commerce/payments")
async def admin_payments(staff: StaffDep, session: StaffSession, payment_status: str | None = Query(default=None, alias="status"), cursor: int = 0, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    rows: list[PaymentAttempt] = []
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            stmt = select(PaymentAttempt).where(PaymentAttempt.tenant_id == tenant_id)
            if payment_status:
                stmt = stmt.where(PaymentAttempt.status == payment_status)
            rows.extend((await tenant_session.execute(stmt)).scalars())
    rows.sort(key=lambda row: row.created_at, reverse=True)
    total = len(rows)
    page_rows = rows[cursor : cursor + limit]
    return _page([{"id": str(row.id), "order_id": str(row.order_id), "tenant_id": str(row.tenant_id), "status": row.status, "gateway": row.gateway, "amount_rial": row.amount_rial, "authority_hint": f"…{row.authority[-8:]}" if row.authority else None, "ref_id": row.ref_id, "created_at": row.created_at, "verified_at": row.verified_at} for row in page_rows], total, cursor, limit)


@router.post("/admin/commerce/payments/{payment_id}/reconcile")
async def reconcile_payment(payment_id: UUID, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, str]:
    tenant_id = await _locate_tenant_record(PaymentAttempt, payment_id)
    async with session_scope(tenant_id) as tenant_session:
        order = await payments.reconcile_attempt(tenant_session, payment_id)
        await audit.record(tenant_session, actor_type="staff", actor_id=staff.id, tenant_id=order.tenant_id, action="payment.reconciled", payload={"payment_id": str(payment_id), "order_id": str(order.id)}, ip=client_ip(request))
        return {"order_id": str(order.id), "status": order.status}


@router.post("/admin/commerce/orders/{order_id}/refunds", status_code=status.HTTP_201_CREATED)
async def create_admin_refund(order_id: UUID, payload: RefundCreate, request: Request, staff: StaffDep, session: StaffSession, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    tenant_id = await _locate_tenant_record(Order, order_id)
    async with session_scope(tenant_id) as tenant_session:
        row = await payments.refund_order(tenant_session, order_id=order_id, amount_toman=payload.amount_toman, method=payload.method, reason=payload.reason, idempotency_key=idempotency_key, created_by=staff.id, payment_attempt_id=payload.payment_attempt_id, external_reference=payload.external_reference)
        await audit.record(tenant_session, actor_type="staff", actor_id=staff.id, tenant_id=row.tenant_id, action="payment.refunded", payload={"refund_id": str(row.id), "order_id": str(row.order_id), "amount_toman": row.amount_toman, "method": row.method, "reason": row.reason}, ip=client_ip(request))
        return {"id": str(row.id), "status": row.status, "amount_toman": row.amount_toman}


@router.get("/admin/commerce/invoices")
async def admin_invoices(staff: StaffDep, session: StaffSession, cursor: int = 0, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    rows: list[Invoice] = []
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            rows.extend((await tenant_session.execute(select(Invoice).where(Invoice.tenant_id == tenant_id))).scalars())
    rows.sort(key=lambda row: row.issued_at, reverse=True)
    total = len(rows)
    return _page([{"id": str(row.id), "order_id": str(row.order_id), "tenant_id": str(row.tenant_id), "number": row.number, "amount_toman": row.amount_toman, "profile": row.profile_snapshot, "issued_at": row.issued_at} for row in rows[cursor : cursor + limit]], total, cursor, limit)


@router.get("/admin/commerce/refunds")
async def admin_refunds(staff: StaffDep, session: StaffSession, cursor: int = 0, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    rows: list[Refund] = []
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            rows.extend((await tenant_session.execute(select(Refund).where(Refund.tenant_id == tenant_id))).scalars())
    rows.sort(key=lambda row: row.created_at, reverse=True)
    total = len(rows)
    return _page([{"id": str(row.id), "order_id": str(row.order_id), "tenant_id": str(row.tenant_id), "amount_toman": row.amount_toman, "status": row.status, "method": row.method, "reason": row.reason, "gateway_reference": row.gateway_reference, "created_at": row.created_at} for row in rows[cursor : cursor + limit]], total, cursor, limit)


@router.get("/admin/commerce/settings")
async def admin_commerce_settings(staff: StaffDep, session: StaffSession) -> dict[str, object]:
    return commerce_settings_public_view(await get_commerce_settings(session))


@router.patch("/admin/commerce/settings")
async def patch_admin_commerce_settings(payload: CommerceSettingsUpdate, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, object]:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    saved = await update_commerce_settings(session, changes)
    safe_changes = {key: ("configured" if key == "zarinpal_merchant_id" else value) for key, value in changes.items()}
    await audit.record(session, actor_type="staff", actor_id=staff.id, action="commerce.settings_update", payload=safe_changes, ip=client_ip(request))
    return commerce_settings_public_view(saved)


@router.post("/admin/commerce/settings/test")
async def test_admin_commerce_settings(staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    current = await get_commerce_settings(session)
    if not current.gateway_enabled or not current.zarinpal_merchant_id:
        raise ApiError("invalid_request", "payment gateway is not fully configured")
    return {"ok": True, "mode": "sandbox" if current.zarinpal_sandbox else "live"}


@router.get("/admin/commerce/installations")
async def admin_installations(staff: StaffDep, session: StaffSession, installation_status: str | None = Query(default=None, alias="status"), cursor: int = 0, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    tenant_names: dict[UUID, str] = {
        tenant_id: name
        for tenant_id, name in (
            await session.execute(select(Tenant.id, Tenant.name))
        ).all()
    }
    rows: list[InstallationRequest] = []
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as tenant_session:
            stmt = select(InstallationRequest).where(InstallationRequest.tenant_id == tenant_id)
            if installation_status:
                stmt = stmt.where(InstallationRequest.status == installation_status)
            rows.extend((await tenant_session.execute(stmt)).scalars())
    rows.sort(key=lambda row: row.created_at, reverse=True)
    total = len(rows)
    items = [{"id": str(row.id), "tenant_id": str(row.tenant_id), "tenant_name": tenant_names.get(row.tenant_id), "order_id": str(row.order_id) if row.order_id else None, "kind": row.kind, "status": row.status, "pbx_type": row.pbx_type, "pbx_version": row.pbx_version, "extension_count": row.extension_count, "connection_method": row.connection_method, "technical_contact": row.technical_contact, "preferred_time": row.preferred_time, "notes": row.notes, "internal_notes": row.internal_notes, "scheduled_at": row.scheduled_at, "created_at": row.created_at} for row in rows[cursor : cursor + limit]]
    return _page(items, total, cursor, limit)


@router.patch("/admin/commerce/installations/{installation_id}")
async def update_admin_installation(installation_id: UUID, payload: InstallationUpdate, request: Request, staff: StaffDep, session: StaffSession) -> dict[str, Any]:
    tenant_id = await _locate_tenant_record(InstallationRequest, installation_id)
    async with session_scope(tenant_id) as tenant_session:
        row = await tenant_session.get(InstallationRequest, installation_id, with_for_update=True)
        if row is None:
            raise ApiError("not_found", "installation request not found")
        changes = payload.model_dump(exclude_unset=True)
        next_status = changes.get("status")
        allowed_transitions = {
            "requested": {"paid", "reviewing", "canceled"},
            "paid": {"reviewing", "scheduled", "canceled"},
            "reviewing": {"scheduled", "in_progress", "canceled"},
            "scheduled": {"in_progress", "canceled"},
            "in_progress": {"completed", "canceled"},
            "completed": set(),
            "canceled": set(),
        }
        if next_status is not None and next_status != row.status and next_status not in allowed_transitions[row.status]:
            raise ApiError("invalid_request", "installation status transition is not allowed")
        for field, value in changes.items():
            setattr(row, field, value)
        row.updated_at = datetime.now(UTC)
        await audit.record(tenant_session, actor_type="staff", actor_id=staff.id, tenant_id=row.tenant_id, action="installation.update", payload={"installation_id": str(row.id), "changes": {key: str(value) if isinstance(value, datetime) else value for key, value in changes.items()}}, ip=client_ip(request))
        return {"id": str(row.id), "status": row.status, "scheduled_at": row.scheduled_at}
