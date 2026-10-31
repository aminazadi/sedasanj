from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import OrgAdminDep, TenantSession, client_ip
from app.errors import ApiError
from app.models import Webhook, WebhookDelivery
from app.schemas import (
    WebhookCreate,
    WebhookCreated,
    WebhookDeliveryOut,
    WebhookOut,
    WebhookTestResult,
    WebhookUpdate,
)
from app.services import audit, ratelimit, webhook_delivery
from app.services.urlguard import assert_safe_webhook_url_async

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])

TEST_TIMEOUT_SECONDS = 10.0
MANAGE_LIMIT_PER_MINUTE = 30
TEST_LIMIT_PER_MINUTE = 10


async def _check_url(url: str) -> None:
    if get_settings().environment == "production" and not url.lower().startswith("https://"):
        raise ApiError("invalid_request", "در محیط عملیاتی فقط نشانی https پذیرفته می‌شود")
    await assert_safe_webhook_url_async(url)


async def _get_owned(session: AsyncSession, tenant_id: UUID | None, webhook_id: UUID) -> Webhook:
    webhook = (
        await session.execute(
            select(Webhook).where(Webhook.id == webhook_id, Webhook.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if webhook is None:
        raise ApiError("not_found", "webhook not found")
    return webhook


async def _send_and_record(
    session: AsyncSession,
    webhook: Webhook,
    payload: dict[str, Any],
    *,
    call_id: UUID | None,
    attempt: int,
) -> WebhookDelivery:
    delivery_id = webhook_delivery.delivery_id_for(webhook.id, str(payload["event"]), call_id)
    async with httpx.AsyncClient(timeout=TEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
        result = await webhook_delivery.post(
            client, webhook, payload, delivery_id=delivery_id, attempt=attempt
        )
    row = WebhookDelivery(
        webhook_id=webhook.id,
        tenant_id=webhook.tenant_id,
        call_id=call_id,
        event=str(payload["event"]),
        payload=payload,
        attempt=attempt,
        status_code=result.status_code,
        delivery_id=delivery_id,
        error=result.error,
        latency_ms=result.latency_ms,
    )
    session.add(row)
    await session.flush()
    return row


@router.get("/events")
async def event_catalog(principal: OrgAdminDep) -> dict[str, Any]:
    """Every event a webhook can receive, plus the envelope and the signature recipe."""
    return {
        "version": webhook_delivery.PAYLOAD_VERSION,
        "subscribable": list(webhook_delivery.SUBSCRIBABLE_EVENTS),
        "events": [
            {"name": name, "description": description}
            for name, description in webhook_delivery.EVENT_CATALOG.items()
        ],
        "envelope": {
            "version": 1,
            "event": "call.complete",
            "timestamp": "2026-01-01T08:00:00Z",
            "tenant_id": "uuid",
            "call_id": "uuid or null",
            "data": {},
        },
        "headers": [
            "X-CBI-Event",
            "X-CBI-Delivery",
            "X-CBI-Attempt",
            "X-CBI-Timestamp",
            "X-CBI-Signature",
            "X-CBI-Signature-Previous",
        ],
        "signature": (
            "X-CBI-Signature = 'sha256=' + hex(HMAC_SHA256(secret, timestamp + '.' + raw_body)); "
            "reject timestamps older than 5 minutes and deduplicate on X-CBI-Delivery."
        ),
    }


@router.post("", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
) -> WebhookCreated:
    assert principal.tenant_id is not None
    await ratelimit.enforce(f"webhook-admin:{principal.tenant_id}", MANAGE_LIMIT_PER_MINUTE)
    count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Webhook)
                .where(Webhook.tenant_id == principal.tenant_id)
            )
        ).scalar_one()
    )
    if count >= get_settings().webhook_max_per_tenant:
        limit = get_settings().webhook_max_per_tenant
        raise ApiError("conflict", f"حداکثر {limit} وب‌هوک مجاز است؛ یکی از قبلی‌ها را حذف کنید")
    await _check_url(str(payload.url))
    secret = payload.secret or secrets.token_urlsafe(32)
    webhook = Webhook(
        tenant_id=principal.tenant_id,
        url=str(payload.url),
        secret=webhook_delivery.seal_secret(secret),
        events=list(payload.events),
        active=True,
        description=payload.description,
    )
    session.add(webhook)
    await session.flush()
    await session.refresh(webhook)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="webhook.create",
        payload={"webhook_id": str(webhook.id), "url": str(payload.url)},
        ip=client_ip(request),
    )
    return WebhookCreated(**WebhookOut.model_validate(webhook).model_dump(), secret=secret)


@router.get("")
async def list_webhooks(
    principal: OrgAdminDep,
    session: TenantSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    base = select(Webhook).where(Webhook.tenant_id == principal.tenant_id)
    total = int(
        (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (await session.execute(base.order_by(Webhook.url).offset(offset).limit(limit))).scalars()
    items = [WebhookOut.model_validate(row) for row in rows]
    next_cursor = str(offset + limit) if offset + len(items) < total else None
    return {"items": items, "total": total, "next_cursor": next_cursor}


@router.get("/{webhook_id}", response_model=WebhookOut)
async def get_webhook(
    webhook_id: UUID, principal: OrgAdminDep, session: TenantSession
) -> WebhookOut:
    return WebhookOut.model_validate(await _get_owned(session, principal.tenant_id, webhook_id))


@router.patch("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookUpdate,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
) -> WebhookOut:
    assert principal.tenant_id is not None
    await ratelimit.enforce(f"webhook-admin:{principal.tenant_id}", MANAGE_LIMIT_PER_MINUTE)
    webhook = await _get_owned(session, principal.tenant_id, webhook_id)
    changes = payload.model_fields_set
    if payload.url is not None:
        await _check_url(str(payload.url))
        webhook.url = str(payload.url)
    if payload.events is not None:
        webhook.events = list(payload.events)
    if "description" in changes:
        webhook.description = payload.description
    if payload.active is not None:
        webhook.active = payload.active
        if payload.active:
            # Re-enabling is the owner's statement that the endpoint works again.
            webhook.consecutive_failures = 0
            webhook.disabled_at = None
            webhook.disabled_reason = None
        elif webhook.disabled_at is None:
            webhook.disabled_at = datetime.now(UTC)
            webhook.disabled_reason = "manual"
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="webhook.update",
        payload={"webhook_id": str(webhook_id), "fields": sorted(changes)},
        ip=client_ip(request),
    )
    return WebhookOut.model_validate(webhook)


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookCreated)
async def rotate_webhook_secret(
    webhook_id: UUID,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
) -> WebhookCreated:
    """New secret now; the old one still signs `X-CBI-Signature-Previous` for 24 hours."""
    assert principal.tenant_id is not None
    await ratelimit.enforce(f"webhook-admin:{principal.tenant_id}", MANAGE_LIMIT_PER_MINUTE)
    webhook = await _get_owned(session, principal.tenant_id, webhook_id)
    secret = secrets.token_urlsafe(32)
    webhook.secret_previous = webhook.secret
    webhook.secret = webhook_delivery.seal_secret(secret)
    webhook.secret_rotated_at = datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="webhook.rotate_secret",
        payload={"webhook_id": str(webhook_id)},
        ip=client_ip(request),
    )
    return WebhookCreated(**WebhookOut.model_validate(webhook).model_dump(), secret=secret)


@router.post("/{webhook_id}/test", response_model=WebhookTestResult)
async def test_webhook(
    webhook_id: UUID, principal: OrgAdminDep, session: TenantSession
) -> WebhookTestResult:
    """Send a signed `webhook.ping` now and report what the endpoint answered."""
    assert principal.tenant_id is not None
    await ratelimit.enforce(f"webhook-test:{principal.tenant_id}", TEST_LIMIT_PER_MINUTE)
    webhook = await _get_owned(session, principal.tenant_id, webhook_id)
    row = await _send_and_record(
        session,
        webhook,
        webhook_delivery.build_ping(principal.tenant_id),
        call_id=None,
        attempt=1,
    )
    return WebhookTestResult(delivery=WebhookDeliveryOut.model_validate(row), ok=row.error is None)


@router.get("/{webhook_id}/deliveries")
async def list_deliveries(
    webhook_id: UUID,
    principal: OrgAdminDep,
    session: TenantSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    failed_only: bool = False,
) -> dict[str, Any]:
    await _get_owned(session, principal.tenant_id, webhook_id)
    base = select(WebhookDelivery).where(
        WebhookDelivery.webhook_id == webhook_id, WebhookDelivery.tenant_id == principal.tenant_id
    )
    if failed_only:
        base = base.where(WebhookDelivery.error.is_not(None))
    total = int(
        (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        await session.execute(
            base.order_by(WebhookDelivery.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars()
    items = [WebhookDeliveryOut.model_validate(row) for row in rows]
    next_cursor = str(offset + limit) if offset + len(items) < total else None
    return {"items": items, "total": total, "next_cursor": next_cursor}


@router.post("/deliveries/{delivery_row_id}/redeliver", response_model=WebhookTestResult)
async def redeliver(
    delivery_row_id: UUID, request: Request, principal: OrgAdminDep, session: TenantSession
) -> WebhookTestResult:
    """Send a stored delivery again to the same webhook with the same `X-CBI-Delivery`."""
    assert principal.tenant_id is not None
    await ratelimit.enforce(f"webhook-test:{principal.tenant_id}", TEST_LIMIT_PER_MINUTE)
    original = (
        await session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.id == delivery_row_id,
                WebhookDelivery.tenant_id == principal.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if original is None:
        raise ApiError("not_found", "delivery not found")
    webhook = await _get_owned(session, principal.tenant_id, original.webhook_id)
    row = await _send_and_record(
        session, webhook, original.payload, call_id=original.call_id, attempt=original.attempt + 1
    )
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="webhook.redeliver",
        payload={"webhook_id": str(webhook.id), "delivery_id": str(row.delivery_id)},
        ip=client_ip(request),
    )
    return WebhookTestResult(delivery=WebhookDeliveryOut.model_validate(row), ok=row.error is None)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
) -> None:
    webhook = await _get_owned(session, principal.tenant_id, webhook_id)
    await session.execute(
        delete(WebhookDelivery).where(
            WebhookDelivery.webhook_id == webhook_id,
            WebhookDelivery.tenant_id == principal.tenant_id,
        )
    )
    await session.delete(webhook)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="webhook.delete",
        payload={"webhook_id": str(webhook_id)},
        ip=client_ip(request),
    )
