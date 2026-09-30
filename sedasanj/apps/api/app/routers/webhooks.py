from __future__ import annotations

import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import delete, func, select

from app.deps import OrgAdminDep, TenantSession, client_ip
from app.errors import ApiError
from app.models import Webhook, WebhookDelivery
from app.schemas import WebhookCreate, WebhookCreated, WebhookOut
from app.services import audit
from app.services.urlguard import assert_safe_webhook_url_async

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
) -> WebhookCreated:
    assert principal.tenant_id is not None
    await assert_safe_webhook_url_async(str(payload.url))
    secret = payload.secret or secrets.token_urlsafe(32)
    webhook = Webhook(
        tenant_id=principal.tenant_id,
        url=str(payload.url),
        secret=secret,
        events=list(payload.events),
        active=True,
    )
    session.add(webhook)
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="webhook.create",
        payload={"webhook_id": str(webhook.id), "url": str(payload.url)},
        ip=client_ip(request),
    )
    return WebhookCreated(
        id=webhook.id,
        url=webhook.url,
        events=webhook.events,
        active=webhook.active,
        secret=secret,
    )


@router.get("")
async def list_webhooks(
    principal: OrgAdminDep,
    session: TenantSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    base = select(Webhook).where(Webhook.tenant_id == principal.tenant_id)
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base.order_by(Webhook.url).offset(offset).limit(limit)
        )
    ).scalars().all()
    items = [WebhookOut.model_validate(row) for row in rows]
    return {"items": items, "total": total, "next_cursor": str(offset + limit) if offset + len(items) < total else None}


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
) -> None:
    webhook = (
        await session.execute(
            select(Webhook).where(
                Webhook.id == webhook_id, Webhook.tenant_id == principal.tenant_id
            )
        )
    ).scalar_one_or_none()
    if webhook is None:
        raise ApiError("not_found", "webhook not found")
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
