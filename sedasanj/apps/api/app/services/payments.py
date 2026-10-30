from __future__ import annotations

import logging
import math
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import routable_tenant_ids, session_scope
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
from app.services import audit, billing, gateway_settings, subscription_state
from app.services.commerce import add_months
from app.services.gateways import (
    AttemptRef,
    Gateway,
    GatewayError,
    PaymentContext,
    Verification,
)
from app.services.gateways.registry import GATEWAY_ORDER, GATEWAYS, build_gateway

logger = logging.getLogger(__name__)

PAID_STATES = {"paid", "partially_refunded", "refunded"}
# A fresh redirect may be re-shown; after this the bank token is considered stale.
REDIRECT_REUSE = timedelta(minutes=10)
# Without a callback nothing can be recovered after this long; the attempt is closed.
ATTEMPT_LIFETIME = timedelta(hours=2)
MAX_CHECKS = 40
CALLBACK_KEYS = ("token", "attempt", "t")


_last_order_ref = 0


def new_order_ref() -> int:
    """Numeric reference unique across tenants (Mellat orderId / SEP ResNum must be unique).

    Milliseconds plus six random digits (< 2**63); strictly increasing inside one process.
    """
    global _last_order_ref
    candidate = int(time.time() * 1000) * 1_000_000 + secrets.randbelow(1_000_000)
    _last_order_ref = max(candidate, _last_order_ref + 1)
    return _last_order_ref


def _attempt_ref(attempt: PaymentAttempt) -> AttemptRef:
    callback = {k: str(v) for k, v in (attempt.callback_json or {}).items()}
    return AttemptRef(
        authority=attempt.authority or "",
        order_ref=int(attempt.order_ref or 0),
        amount_rial=int(attempt.amount_rial),
        callback=callback,
    )


async def _gateway_for(code: str, *, require_enabled: bool = False) -> Gateway:
    """Adapter for a stored attempt; in-flight payments stay verifiable after disabling."""
    if code not in GATEWAYS:
        raise ApiError("not_found", "payment gateway not found")
    state = await gateway_settings.load_one(code)
    if not state.configured or (require_enabled and not state.enabled):
        raise ApiError(
            "payment_method_unavailable",
            "this payment method is not configured; choose another method or contact support",
        )
    return build_gateway(code, state.credentials, sandbox=state.sandbox)


async def available_methods(amount_toman: int | None = None) -> list[dict[str, Any]]:
    """Enabled, fully configured gateways in display order (no credentials)."""
    states = await gateway_settings.load_all()
    methods: list[dict[str, Any]] = []
    for code in GATEWAY_ORDER:
        state = states[code]
        if not state.usable:
            continue
        cls = GATEWAYS[code]
        min_toman = math.ceil(cls.min_rial / 10)
        max_toman = cls.max_rial // 10 if cls.max_rial else None
        available = amount_toman is None or (
            amount_toman >= min_toman and (max_toman is None or amount_toman <= max_toman)
        )
        methods.append(
            {
                "code": code,
                "name": cls.label,
                "description": gateway_settings.DESCRIPTIONS[code],
                "min_toman": min_toman,
                "max_toman": max_toman,
                "available": available,
                "sandbox": state.sandbox,
            }
        )
    return methods


def _callback_url(gateway: str, order: Order, attempt_id: UUID) -> str:
    query = urlencode(
        {"token": order.callback_token, "attempt": str(attempt_id), "t": str(order.tenant_id)}
    )
    return f"{get_settings().public_base_url.rstrip('/')}/v1/payments/{gateway}/callback?{query}"


def redirect_payload(attempt: PaymentAttempt) -> dict[str, Any]:
    spec = (attempt.response_json or {}).get("_redirect") or {}
    return {
        "method": spec.get("method", "GET"),
        "url": spec.get("url", ""),
        "fields": spec.get("fields", {}),
    }


async def initiate(
    session: AsyncSession, order: Order, gateway_code: str | None = None
) -> tuple[PaymentAttempt, dict[str, Any]]:
    if order.status in PAID_STATES:
        raise ApiError("conflict_idempotency", "order is already fulfilled")
    if order.status == "canceled":
        raise ApiError("conflict", "this order was canceled; create a new order")
    states = await gateway_settings.load_all()
    usable = [code for code in GATEWAY_ORDER if states[code].usable]
    if not usable:
        raise ApiError(
            "payment_method_unavailable",
            "no payment method is active; contact support to enable a payment gateway",
        )
    if gateway_code is None:
        if len(usable) != 1:
            raise ApiError("invalid_request", "select a payment method")
        gateway_code = usable[0]
    if gateway_code not in usable:
        raise ApiError(
            "payment_method_unavailable",
            "this payment method is not active; choose another method",
        )
    state = states[gateway_code]
    cls = GATEWAYS[gateway_code]
    amount_rial = order.amount_toman * 10
    if amount_rial < cls.min_rial or (cls.max_rial is not None and amount_rial > cls.max_rial):
        raise ApiError(
            "payment_method_unavailable",
            f"the amount is outside the limits of {cls.label}; choose another payment method",
        )
    now = datetime.now(UTC)
    existing = (
        await session.execute(
            select(PaymentAttempt)
            .where(
                PaymentAttempt.order_id == order.id,
                PaymentAttempt.gateway == gateway_code,
                PaymentAttempt.status == "redirected",
                PaymentAttempt.created_at > now - REDIRECT_REUSE,
            )
            .order_by(PaymentAttempt.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None and redirect_payload(existing)["url"]:
        return existing, redirect_payload(existing)
    gateway = build_gateway(gateway_code, state.credentials, sandbox=state.sandbox)
    attempt_id = uuid4()
    order_ref = new_order_ref()
    context = PaymentContext(
        amount_rial=amount_rial,
        order_ref=order_ref,
        order_number=order.number,
        description=f"سفارش {order.number}",
        callback_url=_callback_url(gateway_code, order, attempt_id),
        mobile=order.customer_mobile,
        email=order.customer_email,
    )
    try:
        started = await gateway.request(context)
    except GatewayError as exc:
        logger.warning(
            "payment request failed",
            extra={"extra_fields": {"gateway": gateway_code, "code": exc.code}},
        )
        raise ApiError(
            "payment_gateway_unavailable" if exc.retryable else "invalid_request",
            f"{cls.label} rejected the request ({exc.message}); try again, "
            "choose another payment method or contact support",
        ) from exc
    redirect = {
        "method": started.redirect.method,
        "url": started.redirect.url,
        "fields": started.redirect.fields,
    }
    attempt = PaymentAttempt(
        id=attempt_id,
        order_id=order.id,
        tenant_id=order.tenant_id,
        gateway=gateway_code,
        status="redirected",
        amount_rial=amount_rial,
        authority=started.token,
        order_ref=order_ref,
        response_json={**started.response, "_redirect": redirect},
    )
    session.add(attempt)
    order.status = "pending_payment"
    await session.flush()
    return attempt, redirect


async def _balance_cache(session: AsyncSession, tenant_id: UUID) -> TenantBalanceCache:
    cache = await session.get(TenantBalanceCache, tenant_id, with_for_update=True)
    if cache is None:
        cache = TenantBalanceCache(tenant_id=tenant_id, seconds=0, toman=0)
        session.add(cache)
        await session.flush()
    return billing.normalize_balance_cache(cache)


def _organization_price_per_minute(
    tenant: Tenant | None,
    subscription: Subscription | None,
    version: PlanVersion,
) -> int:
    return version.overage_price_per_minute_toman


async def grant_credit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    seconds: int,
    source: str,
    source_id: UUID,
    expires_at: datetime | None,
    toman: int,
    idem: str,
) -> None:
    existing = (
        await session.execute(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == tenant_id, LedgerEntry.idempotency_key == idem
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add(
        CreditGrant(
            tenant_id=tenant_id,
            source=source,
            source_id=source_id,
            total_seconds=seconds,
            remaining_seconds=seconds,
            expires_at=expires_at,
        )
    )
    session.add(
        LedgerEntry(
            tenant_id=tenant_id,
            call_id=None,
            kind="subscription_credit" if source == "intro_bonus" else "credit_purchase",
            seconds_delta=seconds,
            toman_delta=toman,
            idempotency_key=idem,
        )
    )
    cache = await _balance_cache(session, tenant_id)
    cache.seconds += seconds
    cache.toman += toman


async def _apply_upgrade(
    session: AsyncSession, order: Order, upgrade_item: OrderItem, now: datetime
) -> None:
    """Apply a paid upgrade; an unusable snapshot fails the change for staff review."""
    subscription = await session.get(
        Subscription, UUID(str(upgrade_item.metadata_json["subscription_id"])), with_for_update=True
    )
    version = await session.get(
        PlanVersion, UUID(str(upgrade_item.metadata_json["target_plan_version_id"]))
    )
    if subscription is None or version is None or subscription.tenant_id != order.tenant_id:
        raise ApiError("internal", "subscription upgrade snapshot is invalid")
    changes = (
        (
            await session.execute(
                select(SubscriptionChange)
                .where(SubscriptionChange.order_id == order.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    days = await subscription_state.grace_days(session)
    usable = (
        subscription.status == "active"
        and subscription_state.is_consuming(subscription, now, days)
        and version.status == "published"
    )
    if not usable:
        for change in changes:
            change.status = "failed"
        await audit.record(
            session,
            actor_type="system",
            tenant_id=order.tenant_id,
            action="subscription.upgrade_failed",
            payload={
                "order_id": str(order.id),
                "subscription_id": str(subscription.id),
                "subscription_status": subscription.status,
                "version_status": version.status,
            },
        )
        logger.error(
            "paid subscription upgrade could not be applied",
            extra={"extra_fields": {"order_id": str(order.id)}},
        )
        return
    tenant = await session.get(Tenant, order.tenant_id, with_for_update=True)
    extra = int(upgrade_item.metadata_json.get("extra_operators", 0))
    for change in changes:
        change.previous_plan_version_id = subscription.plan_version_id
        change.previous_extra_operators = subscription.extra_operators
        change.status = "applied"
    subscription.plan_version_id = version.id
    subscription.base_operators = version.base_operators
    subscription.extra_operators = extra
    subscription.price_per_minute_toman = _organization_price_per_minute(
        tenant, subscription, version
    )
    subscription.assistant_tier = version.assistant_tier
    subscription.assistant_monthly_messages = version.assistant_monthly_messages
    subscription.assistant_source_limit = version.assistant_source_limit
    subscription.assistant_model = version.assistant_model
    subscription.next_plan_version_id = None
    subscription.updated_at = now
    # A pending downgrade belongs to the old plan and no longer applies.
    await subscription_state.close_open_changes(
        session, subscription.id, status="canceled", kinds=("downgrade",)
    )
    if tenant is not None:
        tenant.max_operators = version.base_operators + extra
    await audit.record(
        session,
        actor_type="system",
        tenant_id=order.tenant_id,
        action="subscription.upgraded",
        payload={
            "order_id": str(order.id),
            "subscription_id": str(subscription.id),
            "plan_version_id": str(version.id),
        },
    )


async def fulfill_order(session: AsyncSession, order: Order) -> None:
    if order.status in {"paid", "partially_refunded", "refunded"}:
        return
    items = (
        (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id)))
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    upgrade_item = next((item for item in items if item.kind == "subscription_upgrade"), None)
    if upgrade_item is not None:
        await _apply_upgrade(session, order, upgrade_item, now)
    subscription_item = next((item for item in items if item.kind == "subscription"), None)
    if subscription_item is not None:
        version = await session.get(
            PlanVersion, UUID(str(subscription_item.metadata_json["plan_version_id"]))
        )
        if version is None:
            raise ApiError("internal", "plan version is missing")
        period = str(subscription_item.metadata_json["billing_period"])
        extra = sum(item.quantity for item in items if item.kind == "extra_operator")
        current = (
            await session.execute(
                select(Subscription)
                .where(
                    Subscription.tenant_id == order.tenant_id,
                    Subscription.status.in_(("active", "trialing", "expired", "pending_payment")),
                )
                .order_by(Subscription.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        tenant = await session.get(Tenant, order.tenant_id, with_for_update=True)
        organization_price = _organization_price_per_minute(tenant, current, version)
        current_version = (
            await session.get(PlanVersion, current.plan_version_id) if current else None
        )
        # Early renewal of the same plan extends the paid term and keeps its anniversary, so
        # monthly credits keep their dates; any other purchase starts a fresh term now.
        extends_term = bool(
            current
            and current_version
            and current.status == "active"
            and current.period_end > now
            and current_version.plan_id == version.plan_id
        )
        previous_period_end = current.period_end if extends_term and current else None
        if extends_term and current is not None:
            start = current.period_start
            end = add_months(current.period_end, 12)
        else:
            start = now
            end = add_months(now, 12)
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
            current = Subscription(
                tenant_id=order.tenant_id,
                plan_version_id=version.id,
                status="active",
                billing_period=period,
                period_start=start,
                period_end=end,
                base_operators=version.base_operators,
                extra_operators=extra,
                price_per_minute_toman=organization_price,
                assistant_tier=version.assistant_tier,
                assistant_monthly_messages=version.assistant_monthly_messages,
                assistant_source_limit=version.assistant_source_limit,
                assistant_model=version.assistant_model,
            )
            session.add(current)
        else:
            current.plan_version_id = version.id
            current.status = "active"
            current.billing_period = period
            current.period_start = start
            current.period_end = end
            current.cancel_at_period_end = False
            current.base_operators = version.base_operators
            current.extra_operators = extra
            current.price_per_minute_toman = organization_price
            current.assistant_tier = version.assistant_tier
            current.assistant_monthly_messages = version.assistant_monthly_messages
            current.assistant_source_limit = version.assistant_source_limit
            current.assistant_model = version.assistant_model
            if current.next_plan_version_id == version.id:
                current.next_plan_version_id = None
                scheduled_changes = (
                    (
                        await session.execute(
                            select(SubscriptionChange)
                            .where(
                                SubscriptionChange.subscription_id == current.id,
                                SubscriptionChange.status == "scheduled",
                            )
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                for change in scheduled_changes:
                    change.status = "applied"
            current.updated_at = now
        if tenant is not None:
            tenant.max_operators = version.base_operators + extra
        await session.flush()
        subscription_item.metadata_json = {
            **subscription_item.metadata_json,
            "subscription_id": str(current.id),
            "period_start": current.period_start.isoformat(),
            "period_end": current.period_end.isoformat(),
            "extended_term": extends_term,
            "previous_period_end": previous_period_end.isoformat() if previous_period_end else None,
        }
        if extra:
            session.add(
                SubscriptionExtra(
                    tenant_id=order.tenant_id,
                    subscription_id=current.id,
                    kind="extra_operator",
                    quantity=extra,
                    unit_price_toman=next(
                        item.unit_price_toman for item in items if item.kind == "extra_operator"
                    ),
                    effective_at=start,
                    ends_at=end,
                )
            )
        if first_paid and version.intro_minutes:
            current.intro_credit_issued_at = now
    credit_item = next((item for item in items if item.kind == "credit"), None)
    if credit_item is not None:
        await grant_credit(
            session,
            tenant_id=order.tenant_id,
            seconds=credit_item.quantity * 60,
            source="prepaid",
            source_id=order.id,
            expires_at=None,
            toman=credit_item.total_toman,
            idem=f"credit-order:{order.id}",
        )
    install_item = next((item for item in items if item.kind == "installation"), None)
    if install_item is not None:
        request = (
            await session.execute(
                select(InstallationRequest).where(InstallationRequest.order_id == order.id)
            )
        ).scalar_one_or_none()
        if request is not None:
            request.status = "paid"
            request.updated_at = now
    order.status = "paid"
    order.paid_at = now
    tax_items = [item for item in items if item.kind == "tax"]
    tax_toman = sum(item.total_toman for item in tax_items)
    tax_percent = int(tax_items[0].metadata_json.get("percent", 0)) if tax_items else 0
    session.add(
        Invoice(
            order_id=order.id,
            tenant_id=order.tenant_id,
            number=f"INV-{order.number}",
            amount_toman=order.amount_toman,
            net_toman=order.amount_toman - tax_toman,
            tax_toman=tax_toman,
            tax_percent=tax_percent,
            lines=[
                {
                    "kind": item.kind,
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price_toman": item.unit_price_toman,
                    "total_toman": item.total_toman,
                }
                for item in items
            ],
            profile_snapshot=order.invoice_profile,
        )
    )
    await audit.record(
        session,
        actor_type="system",
        tenant_id=order.tenant_id,
        action="order.fulfilled",
        payload={
            "order_id": str(order.id),
            "kind": order.kind,
            "amount_toman": order.amount_toman,
            "item_kinds": sorted({item.kind for item in items}),
        },
    )


@dataclass(frozen=True)
class CallbackOutcome:
    order_id: UUID | None
    tenant_id: UUID | None
    result: str  # paid | pending | failed | canceled | superseded
    gateway: str


async def _locate_scope(token: str, tenant_hint: UUID | None) -> UUID | None:
    candidates = [tenant_hint] if tenant_hint is not None else await routable_tenant_ids()
    for tenant_id in candidates:
        async with session_scope(tenant_id) as session:
            found = (
                await session.execute(select(Order.id).where(Order.callback_token == token))
            ).scalar_one_or_none()
        if found is not None:
            return tenant_id
    return None


def _matches_token(order: Order, token: str) -> bool:
    return secrets.compare_digest(order.callback_token.encode(), token.encode())


def _result_of(order: Order, attempt: PaymentAttempt) -> str:
    if order.status in PAID_STATES and attempt.status == "verified":
        return "paid"
    if attempt.status == "pending_verification":
        return "pending"
    if attempt.status == "canceled":
        return "canceled"
    if attempt.status == "superseded":
        return "superseded"
    return "failed"


async def _best_effort_reverse(gateway: Gateway, attempt: AttemptRef) -> None:
    if not gateway.supports_reverse:
        return
    try:
        await gateway.reverse(attempt)
    except Exception:  # noqa: BLE001 - the bank also returns unverified payments by itself
        logger.warning(
            "automatic payment reverse failed", extra={"extra_fields": {"gateway": gateway.code}}
        )


async def handle_callback(
    gateway_code: str,
    params: dict[str, str],
    *,
    token: str,
    attempt_id: UUID | None,
    tenant_hint: UUID | None,
) -> CallbackOutcome:
    """Bank return: record, verify, fulfil.  Never raises for payment outcomes."""
    if gateway_code not in GATEWAYS:
        raise ApiError("not_found", "payment gateway not found")
    tenant_id = await _locate_scope(token, tenant_hint)
    if tenant_id is None:
        raise ApiError("not_found", "order not found")
    gateway = await _gateway_for(gateway_code)
    info = gateway.parse_callback(params)

    # Stage A: validate the return and persist it before any bank call.
    async with session_scope(tenant_id) as session:
        order = (
            await session.execute(
                select(Order).where(Order.callback_token == token).with_for_update()
            )
        ).scalar_one_or_none()
        if order is None or not _matches_token(order, token):
            raise ApiError("not_found", "order not found")
        stmt = select(PaymentAttempt).where(
            PaymentAttempt.order_id == order.id, PaymentAttempt.gateway == gateway_code
        )
        if attempt_id is not None:
            stmt = stmt.where(PaymentAttempt.id == attempt_id)
        elif info.token:
            stmt = stmt.where(PaymentAttempt.authority == info.token)
        else:
            raise ApiError("invalid_request", "payment reference is missing")
        attempt = (await session.execute(stmt.with_for_update())).scalar_one_or_none()
        if attempt is None:
            raise ApiError("not_found", "payment attempt not found")
        attempt_pk = attempt.id
        now = datetime.now(UTC)
        attempt.updated_at = now
        if attempt.status == "verified":
            return CallbackOutcome(order.id, tenant_id, _result_of(order, attempt), gateway_code)
        if attempt.status not in {"redirected", "pending_verification", "expired"}:
            return CallbackOutcome(order.id, tenant_id, _result_of(order, attempt), gateway_code)
        # A return that does not match the stored attempt is ignored without touching it:
        # a forged or replayed request must never be able to fail a payment that is real.
        if info.token and attempt.authority and info.token != attempt.authority:
            return CallbackOutcome(order.id, tenant_id, "failed", gateway_code)
        if info.order_ref is not None and info.order_ref != attempt.order_ref:
            return CallbackOutcome(order.id, tenant_id, "failed", gateway_code)
        mismatch_ref: AttemptRef | None = None
        superseded = False
        order_id = order.id
        if order.status in PAID_STATES:
            # Another attempt already paid this order; never verify (and so never settle) this
            # one.  The bank returns unverified money itself; the reverse below is best effort.
            attempt.status, attempt.failure_code = "superseded", "order_already_paid"
            attempt.callback_json = info.reference
            superseded = True
            if info.outcome == "ok":
                mismatch_ref = _attempt_ref(attempt)
        elif info.outcome != "ok":
            if attempt.status == "pending_verification":
                # Already accepted for verification; a replayed failure must not undo that.
                return CallbackOutcome(order.id, tenant_id, "pending", gateway_code)
            attempt.status = "canceled" if info.outcome == "canceled" else "failed"
            attempt.failure_code = info.failure_code
            attempt.callback_json = info.reference
            return CallbackOutcome(order.id, tenant_id, _result_of(order, attempt), gateway_code)
        else:
            attempt.callback_json = info.reference
            if info.amount_rial is not None and info.amount_rial != attempt.amount_rial:
                attempt.status, attempt.failure_code = "failed", "amount_mismatch"
                mismatch_ref = _attempt_ref(attempt)
            else:
                attempt.status = "pending_verification"
    if mismatch_ref is not None:
        await _best_effort_reverse(gateway, mismatch_ref)
    if mismatch_ref is not None or superseded:
        return CallbackOutcome(
            order_id, tenant_id, "superseded" if superseded else "failed", gateway_code
        )

    # Stage B: bank verification and fulfilment in one transaction.
    result = await verify_and_fulfill(tenant_id, attempt_pk)
    return CallbackOutcome(order_id, tenant_id, result, gateway_code)


async def verify_and_fulfill(tenant_id: UUID, attempt_id: UUID) -> str:
    """Idempotent: safe to repeat from the sweeper.  Returns paid | pending | failed."""
    mismatch_ref: AttemptRef | None = None
    gateway: Gateway | None = None
    needs_settle = False
    async with session_scope(tenant_id) as session:
        attempt = await session.get(PaymentAttempt, attempt_id, with_for_update=True)
        if attempt is None:
            raise ApiError("not_found", "payment attempt not found")
        order = await session.get(Order, attempt.order_id, with_for_update=True)
        if order is None:
            raise ApiError("not_found", "order not found")
        if attempt.status == "verified":
            return "paid"
        if attempt.status not in {"pending_verification", "redirected", "expired"}:
            return "failed"
        if order.status in PAID_STATES:
            attempt.status, attempt.failure_code = "superseded", "order_already_paid"
            return "failed"
        gateway = await _gateway_for(attempt.gateway)
        attempt.check_count += 1
        attempt.last_checked_at = datetime.now(UTC)
        try:
            verification = await gateway.verify(_attempt_ref(attempt))
        except GatewayError as exc:
            attempt.status = "pending_verification"
            attempt.failure_code = exc.code
            return "pending"
        attempt.response_json = {**(attempt.response_json or {}), "verify": _safe(verification)}
        if not verification.success:
            attempt.status = "failed"
            attempt.failure_code = verification.code or "verify_failed"
            return "failed"
        if verification.amount_rial is not None and verification.amount_rial != attempt.amount_rial:
            attempt.status, attempt.failure_code = "failed", "amount_mismatch"
            mismatch_ref = _attempt_ref(attempt)
        else:
            now = datetime.now(UTC)
            attempt.status = "verified"
            attempt.failure_code = None
            attempt.ref_id = verification.ref_id or attempt.ref_id
            attempt.rrn = verification.rrn or attempt.rrn
            attempt.card_pan = verification.card_pan or attempt.card_pan
            attempt.verified_at = now
            attempt.settled_at = None if gateway.needs_settle else now
            needs_settle = gateway.needs_settle
            await fulfill_order(session, order)
    if mismatch_ref is not None and gateway is not None:
        await _best_effort_reverse(gateway, mismatch_ref)
        return "failed"
    if needs_settle:
        await settle_attempt(tenant_id, attempt_id)
    return "paid"


def _safe(verification: Verification) -> dict[str, Any]:
    return {
        "code": verification.code,
        "already_verified": verification.already_verified,
        "response": verification.response,
    }


async def settle_attempt(tenant_id: UUID, attempt_id: UUID) -> bool:
    """Mellat bpSettleRequest; repeated until the bank accepts (idempotent)."""
    async with session_scope(tenant_id) as session:
        attempt = await session.get(PaymentAttempt, attempt_id, with_for_update=True)
        if attempt is None or attempt.status != "verified" or attempt.settled_at is not None:
            return True
        gateway = await _gateway_for(attempt.gateway)
        attempt.check_count += 1
        attempt.last_checked_at = datetime.now(UTC)
        try:
            settled = await gateway.settle(_attempt_ref(attempt))
        except GatewayError as exc:
            attempt.failure_code = f"settle_{exc.code}"
            return False
        if settled:
            attempt.settled_at = datetime.now(UTC)
            attempt.failure_code = None
        else:
            attempt.failure_code = "settle_rejected"
        return settled


async def reconcile_attempt(session: AsyncSession, payment_id: UUID) -> Order:
    """Admin action: re-check one attempt with the bank and fulfil when it was really paid."""
    attempt = await session.get(PaymentAttempt, payment_id, with_for_update=True)
    if attempt is None or attempt.authority is None:
        raise ApiError("not_found", "payment attempt not found")
    order = await session.get(Order, attempt.order_id, with_for_update=True)
    if order is None:
        raise ApiError("not_found", "order not found")
    if order.status in PAID_STATES:
        if attempt.status == "verified" and attempt.settled_at is None:
            await _settle_in(session, attempt)
        return order
    gateway = await _gateway_for(attempt.gateway)
    try:
        inquiry = await gateway.inquiry(_attempt_ref(attempt))
    except GatewayError as exc:
        raise ApiError(
            "payment_gateway_unavailable", "the gateway could not be reached; retry in a minute"
        ) from exc
    attempt.last_checked_at = datetime.now(UTC)
    attempt.check_count += 1
    if not inquiry.success:
        attempt.status = "pending_verification" if attempt.status != "failed" else "failed"
        raise ApiError("invalid_request", "payment is not verified by the gateway")
    try:
        verification = await gateway.verify(_attempt_ref(attempt))
    except GatewayError as exc:
        raise ApiError(
            "payment_gateway_unavailable", "verification could not be completed; retry in a minute"
        ) from exc
    attempt.response_json = {**(attempt.response_json or {}), "verify": _safe(verification)}
    if not verification.success or (
        verification.amount_rial is not None and verification.amount_rial != attempt.amount_rial
    ):
        attempt.status = "pending_verification"
        raise ApiError("invalid_request", "payment verification failed")
    now = datetime.now(UTC)
    attempt.status = "verified"
    attempt.failure_code = None
    attempt.ref_id = verification.ref_id or attempt.ref_id
    attempt.rrn = verification.rrn or attempt.rrn
    attempt.card_pan = verification.card_pan or attempt.card_pan
    attempt.verified_at = now
    attempt.settled_at = None if gateway.needs_settle else now
    await fulfill_order(session, order)
    if gateway.needs_settle:
        await _settle_in(session, attempt)
    return order


async def _settle_in(session: AsyncSession, attempt: PaymentAttempt) -> None:
    gateway = await _gateway_for(attempt.gateway)
    try:
        if await gateway.settle(_attempt_ref(attempt)):
            attempt.settled_at = datetime.now(UTC)
            attempt.failure_code = None
    except GatewayError as exc:
        attempt.failure_code = f"settle_{exc.code}"


async def reconcile_pending() -> dict[str, int]:
    """Cron: recover payments whose callback or verification never completed."""
    counts = {"verified": 0, "settled": 0, "expired": 0, "errors": 0}
    now = datetime.now(UTC)
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as session:
            rows = (
                await session.execute(
                    select(
                        PaymentAttempt.id,
                        PaymentAttempt.status,
                        PaymentAttempt.gateway,
                        PaymentAttempt.created_at,
                        PaymentAttempt.settled_at,
                    )
                    .where(
                        (
                            (PaymentAttempt.check_count < MAX_CHECKS)
                            & (
                                (PaymentAttempt.status == "pending_verification")
                                | (
                                    (PaymentAttempt.status == "verified")
                                    & PaymentAttempt.settled_at.is_(None)
                                )
                            )
                        )
                        # Open redirects are always visited so that they can expire.
                        | (
                            (PaymentAttempt.status == "redirected")
                            & (PaymentAttempt.created_at < now - REDIRECT_REUSE)
                        )
                    )
                    .order_by(PaymentAttempt.created_at)
                    .limit(200)
                )
            ).all()
        for attempt_id, state, gateway_code, created_at, _settled in rows:
            try:
                if state == "verified":
                    counts["settled"] += int(await settle_attempt(tenant_id, attempt_id))
                elif state == "pending_verification":
                    outcome = await verify_and_fulfill(tenant_id, attempt_id)
                    counts["verified"] += int(outcome == "paid")
                else:
                    counts["verified"] += await _sweep_redirected(
                        tenant_id, attempt_id, gateway_code, created_at, now, counts
                    )
            except Exception:  # noqa: BLE001 - one bad attempt must not stop the sweep
                counts["errors"] += 1
                logger.exception(
                    "payment reconciliation failed",
                    extra={"extra_fields": {"attempt_id": str(attempt_id)}},
                )
    return counts


async def _sweep_redirected(
    tenant_id: UUID,
    attempt_id: UUID,
    gateway_code: str,
    created_at: datetime,
    now: datetime,
    counts: dict[str, int],
) -> int:
    """No callback seen: ask the bank by token where possible, else expire after 2 hours."""
    paid = False
    if gateway_code in {"zarinpal", "zibal"}:
        try:
            gateway = await _gateway_for(gateway_code)
            async with session_scope(tenant_id) as session:
                attempt = await session.get(PaymentAttempt, attempt_id, with_for_update=True)
                if attempt is None or attempt.status != "redirected":
                    return 0
                if attempt.check_count < MAX_CHECKS:
                    attempt.check_count += 1
                    attempt.last_checked_at = now
                    paid = (await gateway.inquiry(_attempt_ref(attempt))).success
        except (GatewayError, ApiError):
            paid = False
    if paid:
        async with session_scope(tenant_id) as session:
            attempt = await session.get(PaymentAttempt, attempt_id, with_for_update=True)
            if attempt is not None and attempt.status == "redirected":
                attempt.status = "pending_verification"
        return int(await verify_and_fulfill(tenant_id, attempt_id) == "paid")
    if now - created_at > ATTEMPT_LIFETIME:
        async with session_scope(tenant_id) as session:
            attempt = await session.get(PaymentAttempt, attempt_id, with_for_update=True)
            if attempt is not None and attempt.status == "redirected":
                attempt.status = "expired"
                counts["expired"] += 1
    return 0


async def _undo_subscription_effect(
    session: AsyncSession, order: Order, items: Sequence[OrderItem]
) -> None:
    """Reverse what a fully refunded subscription order granted, without over-cancelling."""
    now = datetime.now(UTC)
    upgrade_item = next((item for item in items if item.kind == "subscription_upgrade"), None)
    subscription_item = next((item for item in items if item.kind == "subscription"), None)
    if upgrade_item is not None:
        change = (
            await session.execute(
                select(SubscriptionChange)
                .where(
                    SubscriptionChange.order_id == order.id,
                    SubscriptionChange.status == "applied",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        subscription_id = upgrade_item.metadata_json.get("subscription_id")
        subscription = (
            await session.get(Subscription, UUID(str(subscription_id)), with_for_update=True)
            if subscription_id
            else None
        )
        previous = (
            await session.get(PlanVersion, change.previous_plan_version_id)
            if change and change.previous_plan_version_id
            else None
        )
        if subscription is None or change is None or previous is None:
            logger.error(
                "refunded upgrade could not be reverted; staff must review the subscription",
                extra={"extra_fields": {"order_id": str(order.id)}},
            )
            return
        extra = int(change.previous_extra_operators or 0)
        subscription.plan_version_id = previous.id
        subscription.base_operators = previous.base_operators
        subscription.extra_operators = extra
        subscription.price_per_minute_toman = previous.overage_price_per_minute_toman
        subscription.assistant_tier = previous.assistant_tier
        subscription.assistant_monthly_messages = previous.assistant_monthly_messages
        subscription.assistant_source_limit = previous.assistant_source_limit
        subscription.assistant_model = previous.assistant_model
        subscription.updated_at = now
        change.status = "canceled"
        tenant = await session.get(Tenant, order.tenant_id, with_for_update=True)
        if tenant is not None:
            tenant.max_operators = previous.base_operators + extra
        return
    if subscription_item is None:
        return
    subscription_id = subscription_item.metadata_json.get("subscription_id")
    subscription = (
        await session.get(Subscription, UUID(str(subscription_id)), with_for_update=True)
        if subscription_id
        else None
    )
    if subscription is None:
        return
    previous_end = subscription_item.metadata_json.get("previous_period_end")
    if subscription_item.metadata_json.get("extended_term") and previous_end:
        # An early renewal only added a year: drop it and keep the term that was already paid.
        subscription.period_end = datetime.fromisoformat(str(previous_end))
        subscription.updated_at = now
        return
    subscription.status = "canceled"
    subscription.period_end = now
    subscription.next_plan_version_id = None
    subscription.updated_at = now
    await subscription_state.close_open_changes(session, subscription.id, status="canceled")
    grants = (
        (
            await session.execute(
                select(CreditGrant)
                .where(
                    CreditGrant.tenant_id == order.tenant_id,
                    CreditGrant.source == "monthly_plan",
                    CreditGrant.remaining_seconds > 0,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    revoked = sum(grant.remaining_seconds for grant in grants)
    for grant in grants:
        grant.remaining_seconds = 0
    if revoked:
        cache = await _balance_cache(session, order.tenant_id)
        cache.seconds = max(0, cache.seconds - revoked)
        session.add(
            LedgerEntry(
                tenant_id=order.tenant_id,
                call_id=None,
                kind="refund",
                seconds_delta=-revoked,
                toman_delta=0,
                idempotency_key=f"refund-plan-credit:{order.id}",
            )
        )


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
    if order is None:
        raise ApiError("not_found", "order not found")
    # Replays return the original refund even after the order became fully refunded.
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
    if order.status not in {"paid", "partially_refunded"}:
        raise ApiError("invalid_request", "only paid orders can be refunded")
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

    items = (
        (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id)))
        .scalars()
        .all()
    )
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
            raise ApiError(
                "invalid_request", "gateway reverse must cover the full original payment"
            )
        if payment_attempt_id is None:
            raise ApiError("invalid_request", "payment attempt is required for reverse")
        attempt = await session.get(PaymentAttempt, payment_attempt_id, with_for_update=True)
        if attempt is None or attempt.order_id != order.id or attempt.authority is None:
            raise ApiError("not_found", "payment attempt not found")
        if attempt.status != "verified":
            raise ApiError("invalid_request", "only a verified payment can be reversed")
        gateway = await _gateway_for(attempt.gateway)
        if not gateway.supports_reverse:
            raise ApiError(
                "invalid_request",
                "this gateway cannot reverse payments; use a manual refund instead",
            )
        if attempt.gateway == "zarinpal" and (
            datetime.now(UTC) - (attempt.verified_at or attempt.created_at) > timedelta(minutes=30)
        ):
            raise ApiError("invalid_request", "reverse window has expired")
        try:
            reversed_ok = await gateway.reverse(_attempt_ref(attempt))
        except GatewayError as exc:
            raise ApiError(
                "payment_gateway_unavailable",
                "gateway reverse could not be completed; retry or use a manual refund",
            ) from exc
        if not reversed_ok:
            raise ApiError("invalid_request", "gateway reverse failed")
        response = {"reversed": True}
        external_reference = attempt.ref_id or attempt.authority
        logger.warning(
            "gateway reverse completed; refund record follows",
            extra={
                "extra_fields": {
                    "order_id": str(order.id),
                    "payment_attempt_id": str(attempt.id),
                    "refund_idempotency_key": idempotency_key,
                }
            },
        )
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
    if full_refund:
        await _undo_subscription_effect(session, order, items)
    return row
