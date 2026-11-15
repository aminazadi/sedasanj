"""Cafe Bazaar and Myket purchases for Jalase-Negar, verified on the server.

Both stores sell one-time products here: a plan is one paid month and a pack is a token top-up,
because Myket has no subscription products.  The app sends the purchase token after the store's
own payment sheet; this module asks the store's developer API whether the purchase is real, then
fulfils a normal order through the existing `payments.fulfill_order` so plan terms, credits and
invoices behave exactly like a bank-gateway payment.

Official sources (read 2026-11-15):
- Bazaar OAuth2 token, `…/devapi/v2/auth/token/` with grant_type=refresh_token, and
  `…/devapi/v2/api/validate/<package>/inapp/<sku>/purchases/<token>/`:
  https://developers.cafebazaar.ir/en/guidelines/in-app-billing/api/validation
- Myket `GET https://developer.myket.ir/api/applications/<package>/purchases/products/<sku>/
  tokens/<token>` with the X-Access-Token header (Myket developer console settings).

⚠ needs lab confirmation: live responses of both stores, and the meaning of `consumptionState`
(the two stores document it differently), so consumption is not used as a validity signal; the
unique token hash is what stops a purchase being granted twice.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import control_session_scope, session_scope
from app.errors import ApiError
from app.models import Order, StorePurchase, StoreSku, Tenant, User
from app.routers import token_packages
from app.services import commerce, payments

logger = logging.getLogger(__name__)

STORES = ("bazaar", "myket")
BAZAAR_BASE = "https://pardakht.cafebazaar.ir/devapi/v2"
MYKET_BASE = "https://developer.myket.ir/api"
TIMEOUT = 15.0
PRODUCT = "jalase_negar"

_bazaar_token: tuple[str, float] | None = None


@dataclass(frozen=True)
class StorePurchaseFacts:
    purchased: bool
    developer_payload: str


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unavailable() -> ApiError:
    return ApiError(
        "store_verify_unavailable",
        "تأیید خرید از مارکت اکنون ممکن نیست؛ چند دقیقه بعد دوباره تلاش کنید.",
    )


def _invalid() -> ApiError:
    return ApiError(
        "store_purchase_invalid",
        "مارکت این خرید را تأیید نکرد؛ پرداخت را بررسی و دوباره تلاش کنید.",
    )


async def _bazaar_access_token(client: httpx.AsyncClient) -> str:
    global _bazaar_token
    settings = get_settings()
    if _bazaar_token and _bazaar_token[1] > time.monotonic() + 30:
        return _bazaar_token[0]
    if not (
        settings.bazaar_client_id
        and settings.bazaar_client_secret
        and settings.bazaar_refresh_token
    ):
        raise _unavailable()
    try:
        response = await client.post(
            f"{BAZAAR_BASE}/auth/token/",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.bazaar_client_id,
                "client_secret": settings.bazaar_client_secret,
                "refresh_token": settings.bazaar_refresh_token,
            },
        )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "bazaar token request failed", extra={"extra_fields": {"error": type(exc).__name__}}
        )
        raise _unavailable() from exc
    token = body.get("access_token") if isinstance(body, dict) else None
    if response.status_code != 200 or not isinstance(token, str) or not token:
        logger.error(
            "bazaar token was refused", extra={"extra_fields": {"status": response.status_code}}
        )
        raise _unavailable()
    expires = body.get("expires_in")
    _bazaar_token = (token, time.monotonic() + (expires if isinstance(expires, int) else 600))
    return token


async def _fetch_bazaar(sku: str, token: str, client: httpx.AsyncClient) -> StorePurchaseFacts:
    settings = get_settings()
    access = await _bazaar_access_token(client)
    url = (
        f"{BAZAAR_BASE}/api/validate/{settings.jalase_android_package}/inapp/"
        f"{quote(sku, safe='')}/purchases/{quote(token, safe='')}/"
    )
    try:
        response = await client.get(url, headers={"Authorization": f"Bearer {access}"})
    except httpx.HTTPError as exc:
        raise _unavailable() from exc
    if response.status_code == 404:
        raise _invalid()  # the documented "not_found": the purchase does not exist
    if response.status_code != 200:
        logger.error(
            "bazaar validation failed", extra={"extra_fields": {"status": response.status_code}}
        )
        raise _unavailable()
    return _facts(response)


async def _fetch_myket(sku: str, token: str, client: httpx.AsyncClient) -> StorePurchaseFacts:
    settings = get_settings()
    if not settings.myket_access_token:
        raise _unavailable()
    url = (
        f"{MYKET_BASE}/applications/{settings.jalase_android_package}/purchases/products/"
        f"{quote(sku, safe='')}/tokens/{quote(token, safe='')}"
    )
    try:
        response = await client.get(url, headers={"X-Access-Token": settings.myket_access_token})
    except httpx.HTTPError as exc:
        raise _unavailable() from exc
    if response.status_code in (400, 404):
        raise _invalid()
    if response.status_code != 200:
        logger.error(
            "myket validation failed", extra={"extra_fields": {"status": response.status_code}}
        )
        raise _unavailable()
    return _facts(response)


def _facts(response: httpx.Response) -> StorePurchaseFacts:
    try:
        body: Any = response.json()
    except ValueError as exc:
        raise _unavailable() from exc
    if not isinstance(body, dict):
        raise _unavailable()
    payload = body.get("developerPayload")
    return StorePurchaseFacts(
        purchased=body.get("purchaseState") == 0,
        developer_payload=payload if isinstance(payload, str) else "",
    )


async def fetch_purchase(
    store: str, sku: str, token: str, client: httpx.AsyncClient | None = None
) -> StorePurchaseFacts:
    """Ask the store about one purchase.  Tests pass a client with a mock transport."""
    if store not in STORES:
        raise _invalid()
    if client is not None:
        fetch = _fetch_bazaar if store == "bazaar" else _fetch_myket
        return await fetch(sku, token, client)
    async with httpx.AsyncClient(timeout=TIMEOUT) as own:
        fetch = _fetch_bazaar if store == "bazaar" else _fetch_myket
        return await fetch(sku, token, own)


async def skus(store: str) -> list[dict[str, Any]]:
    async with control_session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(StoreSku).where(StoreSku.store == store, StoreSku.active.is_(True))
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "sku": row.sku,
            "kind": row.kind,
            "plan_code": row.plan_code,
            "package_id": str(row.package_id) if row.package_id else None,
        }
        for row in rows
    ]


async def verify_and_grant(
    *,
    tenant_id: UUID,
    user_id: UUID,
    store: str,
    sku: str,
    purchase_token: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Verify one store purchase and activate what it bought.  Safe to retry."""
    digest = token_hash(purchase_token)
    async with control_session_scope() as control:
        mapping = (
            await control.execute(
                select(StoreSku).where(
                    StoreSku.store == store, StoreSku.sku == sku, StoreSku.active.is_(True)
                )
            )
        ).scalar_one_or_none()
        if mapping is None:
            raise _invalid()
        kind, plan_code, package_id = mapping.kind, mapping.plan_code, mapping.package_id
    async with control_session_scope() as control:
        existing = (
            await control.execute(
                select(StorePurchase).where(
                    StorePurchase.store == store, StorePurchase.token_hash == digest
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.tenant_id != tenant_id:
            raise ApiError(
                "store_purchase_already_used",
                "این خرید قبلاً برای حساب دیگری فعال شده است؛ با همان حساب وارد شوید.",
            )
        if existing is not None and existing.state == "granted":
            return {"status": "granted", "kind": kind, "replayed": True}
        if existing is None:
            control.add(StorePurchase(store=store, token_hash=digest, sku=sku, tenant_id=tenant_id))
            try:
                await control.flush()
            except IntegrityError as exc:
                raise ApiError(
                    "store_purchase_already_used",
                    "این خرید همین الان در حال ثبت است؛ چند ثانیه بعد دوباره تلاش کنید.",
                ) from exc
    try:
        facts = await fetch_purchase(store, sku, purchase_token, client)
        if not facts.purchased or facts.developer_payload != str(tenant_id):
            raise _invalid()
    except ApiError as exc:
        if exc.code == "store_purchase_invalid":
            async with control_session_scope() as control:
                row = (
                    await control.execute(
                        select(StorePurchase).where(
                            StorePurchase.store == store, StorePurchase.token_hash == digest
                        )
                    )
                ).scalar_one_or_none()
                if row is not None and row.state == "pending":
                    await control.delete(row)
        raise
    order_id = await _grant(
        tenant_id=tenant_id,
        user_id=user_id,
        digest=digest,
        kind=kind,
        plan_code=plan_code,
        package_id=package_id,
    )
    async with control_session_scope() as control:
        row = (
            await control.execute(
                select(StorePurchase).where(
                    StorePurchase.store == store, StorePurchase.token_hash == digest
                )
            )
        ).scalar_one()
        row.state = "granted"
        row.order_id = order_id
    return {"status": "granted", "kind": kind, "replayed": False}


async def _grant(
    *,
    tenant_id: UUID,
    user_id: UUID,
    digest: str,
    kind: str,
    plan_code: str | None,
    package_id: UUID | None,
) -> UUID:
    key = f"store-{digest[:48]}"
    async with session_scope(tenant_id) as session:
        tenant = await session.get(Tenant, tenant_id)
        user = await session.get(User, user_id)
        if tenant is None or user is None or tenant.product != PRODUCT:
            raise ApiError("forbidden", "این بخش فقط برای حساب شخصی جلسه‌نگار است.")
        if kind == "plan":
            assert plan_code is not None
            order = await commerce.create_subscription_order(
                session,
                tenant=tenant,
                plan_code=plan_code,
                period="monthly",
                extra_operators=0,
                customer_name=user.display_name or user.email,
                customer_email=user.email,
                customer_mobile=user.mobile_number or "",
                invoice_profile={},
                idempotency_key=key,
                product=PRODUCT,
            )
        else:
            assert package_id is not None
            created = await token_packages.create_pack_order(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                package_id=package_id,
                idempotency_key=key,
                product=PRODUCT,
                ip=None,
            )
            pack_order = await session.get(Order, UUID(created["id"]))
            assert pack_order is not None
            order = pack_order
        await payments.fulfill_order(session, order)
        return order.id
