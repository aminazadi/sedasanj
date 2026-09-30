from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import ApiError
from app.models import (
    CreditGrant,
    InstallationRequest,
    Invoice,
    LedgerEntry,
    Order,
    OrderItem,
    PaymentAttempt,
    PlanVersion,
    Refund,
    Subscription,
    SubscriptionChange,
    SubscriptionExtra,
    Tenant,
    TenantBalanceCache,
)
from app.services import billing
from app.services.commerce import add_months
from app.services.commerce_settings import CommerceSettings, get_commerce_settings


@dataclass(frozen=True)
class GatewayRequest:
    authority: str
    url: str
    response: dict[str, Any]


@dataclass(frozen=True)
class GatewayVerification:
    success: bool
    ref_id: str | None
    response: dict[str, Any]


class PaymentGateway(Protocol):
    async def request(self, *, amount_rial: int, description: str, callback_url: str, mobile: str, email: str) -> GatewayRequest: ...
    async def verify(self, *, amount_rial: int, authority: str) -> GatewayVerification: ...
    async def query(self, *, amount_rial: int, authority: str) -> GatewayVerification: ...


class ZarinpalGateway:
    def __init__(self, settings: CommerceSettings | None = None) -> None:
        runtime = get_settings()
        merchant_id = settings.zarinpal_merchant_id if settings else (runtime.zarinpal_merchant_id or "")
        sandbox = settings.zarinpal_sandbox if settings else runtime.zarinpal_sandbox
        enabled = settings.gateway_enabled if settings else bool(merchant_id)
        if not enabled or not merchant_id:
            raise ApiError("invalid_request", "ZarinPal merchant id is not configured")
        self.merchant_id = merchant_id
        self.base = "https://sandbox.zarinpal.com" if sandbox else "https://api.zarinpal.com"
        self.start = "https://sandbox.zarinpal.com" if sandbox else "https://www.zarinpal.com"

    async def _post(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.post(f"{self.base}/pg/v4/payment/{action}.json", json=payload)
        try:
            body = response.json()
        except ValueError as exc:
            raise ApiError("internal", "invalid response from payment gateway", retryable=True) from exc
        if response.status_code >= 500:
            raise ApiError("internal", "payment gateway is unavailable", retryable=True)
        if not isinstance(body, dict):
            raise ApiError("internal", "invalid response from payment gateway", retryable=True)
        return body

    async def request(self, *, amount_rial: int, description: str, callback_url: str, mobile: str, email: str) -> GatewayRequest:
        body = await self._post("request", {"merchant_id": self.merchant_id, "amount": amount_rial, "description": description, "callback_url": callback_url, "metadata": {"mobile": mobile, "email": email}})
        data = body.get("data") or {}
        authority = data.get("authority")
        if data.get("code") != 100 or not authority:
            raise ApiError("invalid_request", str((body.get("errors") or {}).get("message") or "payment request failed"))
        return GatewayRequest(str(authority), f"{self.start}/pg/StartPay/{authority}", body)

    async def verify(self, *, amount_rial: int, authority: str) -> GatewayVerification:
        body = await self._post("verify", {"merchant_id": self.merchant_id, "amount": amount_rial, "authority": authority})
        data = body.get("data") or {}
        code = data.get("code")
        return GatewayVerification(code in {100, 101}, str(data.get("ref_id")) if data.get("ref_id") is not None else None, body)

    async def query(self, *, amount_rial: int, authority: str) -> GatewayVerification:
        body = await self._post("inquiry", {"merchant_id": self.merchant_id, "authority": authority})
        data = body.get("data") or {}
        status = str(data.get("status") or "")
        return GatewayVerification(status in {"VERIFIED", "PAID"}, None, body)

    async def reverse(self, *, authority: str) -> GatewayVerification:
        body = await self._post("reverse", {"merchant_id": self.merchant_id, "authority": authority})
        data = body.get("data") or {}
        return GatewayVerification(data.get("code") == 100, None, body)


async def initiate(session: AsyncSession, order: Order) -> tuple[PaymentAttempt, str]:
    if order.status in {"paid", "partially_refunded", "refunded"}:
        raise ApiError("conflict_idempotency", "order is already fulfilled")
    # Repeating the pay action before the customer returns from the gateway must
    # not create another authority.  An authority is already sufficient to
    # resume the same ZarinPal checkout URL.
    existing = (
        await session.execute(
            select(PaymentAttempt)
            .where(
                PaymentAttempt.order_id == order.id,
                PaymentAttempt.gateway == "zarinpal",
                PaymentAttempt.status == "redirected",
                PaymentAttempt.authority.is_not(None),
            )
            .order_by(PaymentAttempt.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.authority is not None:
        gateway = ZarinpalGateway(await get_commerce_settings(session))
        return existing, f"{gateway.start}/pg/StartPay/{existing.authority}"
    amount_rial = order.amount_toman * 10
    callback = f"{get_settings().public_base_url.rstrip('/')}/v1/payments/zarinpal/callback?token={order.callback_token}"
    result = await ZarinpalGateway(await get_commerce_settings(session)).request(amount_rial=amount_rial, description=f"سفارش {order.number}", callback_url=callback, mobile=order.customer_mobile, email=order.customer_email)
    attempt = PaymentAttempt(order_id=order.id, tenant_id=order.tenant_id, gateway="zarinpal", status="redirected", amount_rial=amount_rial, authority=result.authority, response_json=result.response)
    session.add(attempt)
    order.status = "pending_payment"
    await session.flush()
    return attempt, result.url


async def _balance_cache(session: AsyncSession, tenant_id: UUID) -> TenantBalanceCache:
    cache = await session.get(TenantBalanceCache, tenant_id, with_for_update=True)
    if cache is None:
        cache = TenantBalanceCache(tenant_id=tenant_id, seconds=0, toman=0)
        session.add(cache)
        await session.flush()
    return billing.normalize_balance_cache(cache)


async def grant_credit(session: AsyncSession, *, tenant_id: UUID, seconds: int, source: str, source_id: UUID, expires_at: datetime | None, toman: int, idem: str) -> None:
    existing = (await session.execute(select(LedgerEntry).where(LedgerEntry.tenant_id == tenant_id, LedgerEntry.idempotency_key == idem))).scalar_one_or_none()
    if existing is not None:
        return
    session.add(CreditGrant(tenant_id=tenant_id, source=source, source_id=source_id, total_seconds=seconds, remaining_seconds=seconds, expires_at=expires_at))
    session.add(LedgerEntry(tenant_id=tenant_id, call_id=None, kind="subscription_credit" if source == "intro_bonus" else "credit_purchase", seconds_delta=seconds, toman_delta=toman, idempotency_key=idem))
    cache = await _balance_cache(session, tenant_id)
    cache.seconds += seconds
    cache.toman += toman


async def fulfill_order(session: AsyncSession, order: Order) -> None:
    if order.status in {"paid", "partially_refunded", "refunded"}:
        return
    items = (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    now = datetime.now(UTC)
    upgrade_item = next((item for item in items if item.kind == "subscription_upgrade"), None)
    if upgrade_item is not None:
        subscription = await session.get(Subscription, UUID(str(upgrade_item.metadata_json["subscription_id"])), with_for_update=True)
        version = await session.get(PlanVersion, UUID(str(upgrade_item.metadata_json["target_plan_version_id"])))
        if subscription is None or version is None or subscription.tenant_id != order.tenant_id:
            raise ApiError("internal", "subscription upgrade snapshot is invalid")
        extra = int(upgrade_item.metadata_json.get("extra_operators", 0))
        subscription.plan_version_id = version.id
        subscription.base_operators = version.base_operators
        subscription.extra_operators = extra
        subscription.price_per_minute_toman = version.overage_price_per_minute_toman
        subscription.assistant_tier = version.assistant_tier
        subscription.assistant_monthly_messages = version.assistant_monthly_messages
        subscription.assistant_source_limit = version.assistant_source_limit
        subscription.assistant_model = version.assistant_model
        subscription.updated_at = now
        tenant = await session.get(Tenant, order.tenant_id, with_for_update=True)
        if tenant is not None:
            tenant.max_operators = version.base_operators + extra
            tenant.price_per_minute_toman = version.overage_price_per_minute_toman
        changes = (await session.execute(select(SubscriptionChange).where(SubscriptionChange.order_id == order.id).with_for_update())).scalars().all()
        for change in changes:
            change.status = "applied"
    subscription_item = next((item for item in items if item.kind == "subscription"), None)
    if subscription_item is not None:
        version = await session.get(PlanVersion, UUID(str(subscription_item.metadata_json["plan_version_id"])))
        if version is None:
            raise ApiError("internal", "plan version is missing")
        period = str(subscription_item.metadata_json["billing_period"])
        extra = sum(item.quantity for item in items if item.kind == "extra_operator")
        current = (await session.execute(select(Subscription).where(Subscription.tenant_id == order.tenant_id, Subscription.status.in_(("active", "trialing", "expired", "pending_payment"))).order_by(Subscription.created_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
        start = current.period_end if current and current.status == "active" and current.period_end > now else now
        end = add_months(start, 12 if period == "annual" else 1)
        # A bonus belongs only to the first paid activation.  In particular,
        # migrated legacy subscriptions have no historical bonus timestamp but
        # must never receive one on their first renewal.
        first_paid = (
            current is None
            or current.status == "pending_payment"
            or current.billing_period == "trial"
        )
        if current is None or current.billing_period == "trial":
            if current is not None:
                current.status = "canceled"
            current = Subscription(tenant_id=order.tenant_id, plan_version_id=version.id, status="active", billing_period=period, period_start=start, period_end=end, base_operators=version.base_operators, extra_operators=extra, price_per_minute_toman=version.overage_price_per_minute_toman, assistant_tier=version.assistant_tier, assistant_monthly_messages=version.assistant_monthly_messages, assistant_source_limit=version.assistant_source_limit, assistant_model=version.assistant_model)
            session.add(current)
        else:
            current.plan_version_id = version.id
            current.status = "active"
            current.billing_period = period
            current.period_start = start
            current.period_end = end
            current.base_operators = version.base_operators
            current.extra_operators = extra
            current.price_per_minute_toman = version.overage_price_per_minute_toman
            current.assistant_tier = version.assistant_tier
            current.assistant_monthly_messages = version.assistant_monthly_messages
            current.assistant_source_limit = version.assistant_source_limit
            current.assistant_model = version.assistant_model
            if current.next_plan_version_id == version.id:
                current.next_plan_version_id = None
                scheduled_changes = (await session.execute(select(SubscriptionChange).where(SubscriptionChange.subscription_id == current.id, SubscriptionChange.status == "scheduled").with_for_update())).scalars().all()
                for change in scheduled_changes:
                    change.status = "applied"
            current.updated_at = now
        tenant = await session.get(Tenant, order.tenant_id, with_for_update=True)
        if tenant is not None:
            tenant.max_operators = version.base_operators + extra
            tenant.price_per_minute_toman = version.overage_price_per_minute_toman
        await session.flush()
        subscription_item.metadata_json = {
            **subscription_item.metadata_json,
            "subscription_id": str(current.id),
            "period_start": current.period_start.isoformat(),
            "period_end": current.period_end.isoformat(),
        }
        if extra:
            session.add(SubscriptionExtra(tenant_id=order.tenant_id, subscription_id=current.id, kind="extra_operator", quantity=extra, unit_price_toman=next(item.unit_price_toman for item in items if item.kind == "extra_operator"), effective_at=start, ends_at=end))
        if first_paid and version.intro_minutes:
            await grant_credit(session, tenant_id=order.tenant_id, seconds=version.intro_minutes * 60, source="intro_bonus", source_id=current.id, expires_at=now + timedelta(days=30), toman=0, idem=f"intro:{current.id}")
            current.intro_credit_issued_at = now
    credit_item = next((item for item in items if item.kind == "credit"), None)
    if credit_item is not None:
        await grant_credit(session, tenant_id=order.tenant_id, seconds=credit_item.quantity * 60, source="prepaid", source_id=order.id, expires_at=None, toman=order.amount_toman, idem=f"credit-order:{order.id}")
    install_item = next((item for item in items if item.kind == "installation"), None)
    if install_item is not None:
        request = (await session.execute(select(InstallationRequest).where(InstallationRequest.order_id == order.id))).scalar_one_or_none()
        if request is not None:
            request.status = "paid"
            request.updated_at = now
    order.status = "paid"
    order.paid_at = now
    session.add(Invoice(order_id=order.id, tenant_id=order.tenant_id, number=f"INV-{order.number}", amount_toman=order.amount_toman, profile_snapshot=order.invoice_profile))


async def verify_callback(session: AsyncSession, *, token: str, authority: str, status: str) -> Order:
    order = (await session.execute(select(Order).where(Order.callback_token == token).with_for_update())).scalar_one_or_none()
    if order is None:
        raise ApiError("not_found", "order not found")
    if order.status in {"paid", "partially_refunded", "refunded"}:
        return order
    attempt = (await session.execute(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id, PaymentAttempt.authority == authority).order_by(PaymentAttempt.created_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
    if attempt is None:
        raise ApiError("invalid_request", "payment authority does not match the order")
    if status.upper() != "OK":
        attempt.status = "canceled"
        order.status = "canceled"
        return order
    try:
        result = await ZarinpalGateway(await get_commerce_settings(session)).verify(amount_rial=order.amount_toman * 10, authority=authority)
    except ApiError:
        attempt.status = "pending_verification"
        raise
    attempt.response_json = result.response
    if not result.success:
        attempt.status = "failed"
        raise ApiError("invalid_request", "payment verification failed")
    attempt.status = "verified"
    attempt.ref_id = result.ref_id
    attempt.verified_at = datetime.now(UTC)
    await fulfill_order(session, order)
    return order


async def reconcile_attempt(session: AsyncSession, payment_id: UUID) -> Order:
    attempt = await session.get(PaymentAttempt, payment_id, with_for_update=True)
    if attempt is None or attempt.authority is None:
        raise ApiError("not_found", "payment attempt not found")
    order = await session.get(Order, attempt.order_id, with_for_update=True)
    if order is None:
        raise ApiError("not_found", "order not found")
    if order.status in {"paid", "partially_refunded", "refunded"}:
        return order
    gateway = ZarinpalGateway(await get_commerce_settings(session))
    inquiry = await gateway.query(
        amount_rial=attempt.amount_rial,
        authority=attempt.authority,
    )
    attempt.response_json = inquiry.response
    if not inquiry.success:
        attempt.status = "pending_verification"
        raise ApiError("invalid_request", "payment is not verified")
    result = await gateway.verify(amount_rial=attempt.amount_rial, authority=attempt.authority)
    attempt.response_json = result.response
    if not result.success:
        attempt.status = "pending_verification"
        raise ApiError("invalid_request", "payment verification failed")
    attempt.status = "verified"
    attempt.ref_id = result.ref_id
    attempt.verified_at = datetime.now(UTC)
    await fulfill_order(session, order)
    return order


async def refund_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    amount_toman: int,
    method: str,
    reason: str,
    idempotency_key: str,
    created_by: UUID,
    payment_attempt_id: UUID | None = None,
    external_reference: str | None = None,
) -> Refund:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None or order.status not in {"paid", "partially_refunded"}:
        raise ApiError("invalid_request", "only paid orders can be refunded")
    existing = (
        await session.execute(
            select(Refund).where(
                Refund.tenant_id == order.tenant_id,
                Refund.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    refunded = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(Refund.amount_toman), 0)).where(
                    Refund.order_id == order.id,
                    Refund.status == "completed",
                )
            )
        ).scalar_one()
    )
    if amount_toman > order.amount_toman - refunded:
        raise ApiError("invalid_request", "refund exceeds the remaining paid amount")

    items = (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    credit_item = next((item for item in items if item.kind == "credit"), None)
    seconds_to_revoke = 0
    grant: CreditGrant | None = None
    if credit_item is not None:
        seconds_to_revoke = math.ceil(credit_item.quantity * 60 * amount_toman / order.amount_toman)
        grant = (
            await session.execute(
                select(CreditGrant)
                .where(
                    CreditGrant.tenant_id == order.tenant_id,
                    CreditGrant.source == "prepaid",
                    CreditGrant.source_id == order.id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if grant is None or grant.remaining_seconds < seconds_to_revoke:
            raise ApiError("invalid_request", "purchased credit has already been consumed")

    attempt: PaymentAttempt | None = None
    response: dict[str, Any] = {}
    if method == "reverse":
        if refunded or amount_toman != order.amount_toman:
            raise ApiError("invalid_request", "gateway reverse must cover the full original payment")
        if payment_attempt_id is None:
            raise ApiError("invalid_request", "payment attempt is required for reverse")
        attempt = await session.get(PaymentAttempt, payment_attempt_id, with_for_update=True)
        if attempt is None or attempt.order_id != order.id or attempt.authority is None:
            raise ApiError("not_found", "payment attempt not found")
        if datetime.now(UTC) - attempt.created_at > timedelta(minutes=30):
            raise ApiError("invalid_request", "reverse window has expired")
        result = await ZarinpalGateway(await get_commerce_settings(session)).reverse(
            authority=attempt.authority
        )
        response = result.response
        if not result.success:
            raise ApiError("invalid_request", "gateway reverse failed")
        external_reference = attempt.ref_id or attempt.authority
    elif method != "manual":
        raise ApiError("invalid_request", "refund method is invalid")

    row = Refund(
        order_id=order.id,
        payment_attempt_id=attempt.id if attempt else payment_attempt_id,
        tenant_id=order.tenant_id,
        amount_toman=amount_toman,
        status="completed",
        method=method,
        reason=reason.strip(),
        idempotency_key=idempotency_key,
        gateway_reference=external_reference,
        response_json=response,
        created_by=created_by,
        completed_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    if grant is not None and seconds_to_revoke:
        grant.remaining_seconds -= seconds_to_revoke
        cache = await _balance_cache(session, order.tenant_id)
        cache.seconds = max(0, cache.seconds - seconds_to_revoke)
        cache.toman = max(0, cache.toman - amount_toman)
        session.add(
            LedgerEntry(
                tenant_id=order.tenant_id,
                call_id=None,
                kind="refund",
                seconds_delta=-seconds_to_revoke,
                toman_delta=-amount_toman,
                idempotency_key=f"refund:{row.id}",
            )
        )
    full_refund = refunded + amount_toman == order.amount_toman
    order.status = "refunded" if full_refund else "partially_refunded"
    subscription_item = next(
        (item for item in items if item.kind in {"subscription", "subscription_upgrade"}), None
    )
    if full_refund and subscription_item is not None:
        subscription_id = subscription_item.metadata_json.get("subscription_id")
        subscription = (
            await session.get(Subscription, UUID(str(subscription_id)), with_for_update=True)
            if subscription_id
            else None
        )
        if subscription is not None:
            subscription.status = "canceled"
            subscription.period_end = datetime.now(UTC)
            subscription.updated_at = datetime.now(UTC)
    return row
