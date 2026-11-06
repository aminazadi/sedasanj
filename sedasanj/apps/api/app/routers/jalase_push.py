"""Public installation and super-admin push endpoints."""

import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, SecretStr, StringConstraints
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.deps import PublicSession, StaffSession, SuperAdminDep, client_ip, current_api_key
from app.errors import ApiError
from app.models import (
    ApiKey,
    JalasePushCampaign,
    JalasePushDelivery,
    JalasePushInstallation,
    JalasePushSettings,
)
from app.schemas import StaffSensitiveAction
from app.security import hash_api_key
from app.services import audit, ratelimit
from app.services import jalase_push as push
from app.services.platform_secrets import encrypt_secret

router = APIRouter(tags=["jalase-negar push"])
PUBLIC = "/v1/jalase-negar/push/installations"
ADMIN = "/v1/admin/jalase-negar/push"
InstallSecret = Annotated[str, Header(alias="X-Installation-Secret", min_length=43, max_length=128)]
MobileSecret = Annotated[str | None, Header(alias="X-Api-Key", max_length=512)]


class Registration(BaseModel):
    token: Annotated[
        str, StringConstraints(min_length=16, max_length=2048, pattern=r"^[A-Za-z0-9_:.\-]+$")
    ]
    version: push.Version
    channel: push.Channel
    enabled: bool


class SettingsIn(StaffSensitiveAction):
    enabled: bool
    project: push.Project
    credentials: SecretStr | None = None


def denied() -> ApiError:
    return ApiError("jalase_push_installation", "اپ را دوباره باز کنید و اتصال پوش را بررسی کنید.")


def checked_secret(row: JalasePushInstallation | None, secret: str) -> JalasePushInstallation:
    if row is None or not hmac.compare_digest(row.secret_hash, hash_api_key(secret)):
        raise denied()
    return row


@router.put(PUBLIC + "/{installation_id}", status_code=204)
async def register(
    installation_id: UUID,
    payload: Registration,
    request: Request,
    session: PublicSession,
    secret: InstallSecret,
    mobile: MobileSecret = None,
) -> Response:
    await ratelimit.enforce(f"push-register:{client_ip(request) or 'unknown'}", 120)
    key_id = None
    if mobile:
        try:
            principal = await current_api_key(request, x_api_key=mobile)
        except ApiError as error:
            if error.status_code not in (401, 403, 404, 423):
                raise
        else:
            if principal.key_kind == "mobile" and "meetings:write" in principal.scopes:
                key_id = principal.id
    secret_hash = hash_api_key(secret)
    try:
        token = encrypt_secret(payload.token)
    except RuntimeError:
        raise push.unavailable() from None
    values = {
        "token": token,
        "token_hash": hash_api_key(payload.token),
        "mobile_key_id": key_id,
        "version": payload.version,
        "channel": payload.channel,
        "enabled": payload.enabled,
        "seen_at": datetime.now(UTC),
    }
    try:
        stmt = insert(JalasePushInstallation).values(
            id=installation_id, secret_hash=secret_hash, **values
        )
        installed = await session.scalar(
            stmt.on_conflict_do_update(
                index_elements=[JalasePushInstallation.id],
                set_={**values, "invalidated": False},
                where=(
                    (JalasePushInstallation.secret_hash == secret_hash)
                    & or_(
                        JalasePushInstallation.invalidated.is_(False),
                        JalasePushInstallation.token_hash != values["token_hash"],
                    )
                ),
            ).returning(JalasePushInstallation.id)
        )
    except IntegrityError:
        raise denied() from None
    if installed is None:
        row = checked_secret(await session.get(JalasePushInstallation, installation_id), secret)
        if row.invalidated:
            raise ApiError("jalase_push_token_expired", "اپ را باز کنید تا شناسهٔ پوش تازه شود.")
        raise denied()
    return Response(status_code=204)


@router.delete(PUBLIC + "/{installation_id}", status_code=204)
async def remove(
    installation_id: UUID, request: Request, session: PublicSession, secret: InstallSecret
) -> Response:
    await ratelimit.enforce(f"push-register:{client_ip(request) or 'unknown'}", 120)
    row = checked_secret(await session.get(JalasePushInstallation, installation_id), secret)
    await session.delete(row)
    return Response(status_code=204)


@router.get(PUBLIC + "/{installation_id}/messages/{campaign_id}")
async def message(
    installation_id: UUID,
    campaign_id: UUID,
    request: Request,
    response: Response,
    session: PublicSession,
    secret: InstallSecret,
    mobile: MobileSecret = None,
) -> dict[str, Any]:
    await ratelimit.enforce(f"push-fetch:{client_ip(request) or 'unknown'}", 240)
    row = checked_secret(await session.get(JalasePushInstallation, installation_id), secret)
    campaign = await session.get(JalasePushCampaign, campaign_id)
    delivery = await session.get(JalasePushDelivery, (campaign_id, installation_id))
    now = datetime.now(UTC)
    if (
        campaign is None
        or campaign.cancelled_at is not None
        or campaign.expires_at <= now
        or delivery is None
        or delivery.state not in ("sending", "accepted", "unknown")
    ):
        raise denied()
    audience = push.Audience.model_validate(campaign.payload["audience"])
    if audience.kind in ("organization", "user"):
        if not mobile or not row.mobile_key_id:
            raise denied()
        principal = await current_api_key(request, x_api_key=mobile)
        if principal.key_kind != "mobile" or principal.id != row.mobile_key_id:
            raise denied()
    eligible = await session.scalar(
        push.recipients(audience, now).where(JalasePushInstallation.id == installation_id)
    )
    if eligible is None:
        raise denied()
    response.headers["Cache-Control"] = "no-store"
    return dict(campaign.payload["message"])


async def record(
    session: StaffSession, principal: SuperAdminDep, action: str, **payload: Any
) -> None:
    await audit.record(
        session,
        actor_type="staff",
        actor_id=principal.id,
        tenant_id=None,
        action=f"jalase_push.{action}",
        payload=payload,
    )


def settings_view(config: JalasePushSettings | None) -> dict[str, Any]:
    return {
        "enabled": bool(config and config.enabled),
        "project": config.project if config else "",
        "configured": bool(config and config.credentials),
    }


@router.get(ADMIN + "/settings")
async def read_settings(session: StaffSession, _: SuperAdminDep) -> dict[str, Any]:
    return settings_view(await push.settings(session))


@router.put(ADMIN + "/settings")
async def save_settings(
    payload: SettingsIn, session: StaffSession, principal: SuperAdminDep
) -> dict[str, Any]:
    from app.routers.admin import _verify_sensitive_staff_action

    await ratelimit.enforce(f"push-settings:{principal.id}", 12)
    await _verify_sensitive_staff_action(
        session, principal, payload.current_password, payload.totp_code
    )
    await session.execute(text("SELECT pg_advisory_xact_lock(8360121)"))
    config = await push.settings(session)
    if config is None:
        config = JalasePushSettings(id=1)
        session.add(config)
    if payload.credentials is not None:
        raw = payload.credentials.get_secret_value()
        if len(raw) > 16000:
            raise push.invalid()
        validated = push.credentials_json(raw, payload.project)
        try:
            config.credentials = encrypt_secret(
                json.dumps({**validated, "project_id": payload.project, "type": "service_account"})
            )
        except RuntimeError:
            raise push.unavailable() from None
    elif config.project != payload.project:
        config.credentials = None
    if payload.enabled and not config.credentials:
        raise push.unavailable()
    config.project = payload.project
    config.enabled = payload.enabled
    await record(session, principal, "settings", enabled=config.enabled, project=config.project)
    return settings_view(config)


@router.post(ADMIN + "/settings/check", status_code=204)
async def check_settings(session: StaffSession, principal: SuperAdminDep) -> Response:
    await ratelimit.enforce(f"push-check:{principal.id}", 12)
    config = await push.settings(session)
    if config is None:
        raise push.unavailable()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            firebase = push.Firebase(client, config)
            await firebase.authenticate()
            result = await firebase.send(
                {"topic": "jalase-negar-validation", "data": {"check": "1"}}, validate_only=True
            )
            if not result.is_success:
                raise push.unavailable()
    except (httpx.HTTPError, ValueError, RuntimeError):
        raise push.unavailable() from None
    return Response(status_code=204)


@router.post(ADMIN + "/preview")
async def preview(payload: push.Compose, session: StaffSession, _: SuperAdminDep) -> dict[str, int]:
    audience = push.recipients(payload.audience, datetime.now(UTC)).subquery()
    count = await session.scalar(select(func.count()).select_from(audience))
    return {"count": count or 0}


async def enqueue(
    payload: push.Send, session: StaffSession, principal: SuperAdminDep, *, test: bool = False
) -> dict[str, UUID]:
    if payload.audience.kind == "all" and not payload.confirmed_all:
        raise push.invalid()
    await ratelimit.enforce(f"push-send:{principal.id}", 30)
    content = payload.model_dump(mode="json", include={"audience", "message", "scheduled_at"})
    existing = await session.get(JalasePushCampaign, payload.id)
    if existing is not None:
        if existing.actor_id != principal.id or existing.payload != content:
            raise push.invalid()
        return {"id": payload.id}
    now = datetime.now(UTC)
    if payload.scheduled_at and not (
        now - timedelta(seconds=5) <= payload.scheduled_at <= now + timedelta(days=365)
    ):
        raise ApiError("jalase_push_invalid", "زمان ارسال را در بازهٔ یک سال آینده انتخاب کنید.")
    scheduled_at = max(payload.scheduled_at or now, now)
    config = await push.settings(session)
    if not config or not config.enabled or not config.credentials:
        raise push.unavailable()
    created = await session.scalar(
        insert(JalasePushCampaign)
        .values(
            id=payload.id,
            actor_id=principal.id,
            payload=content,
            scheduled_at=scheduled_at,
            expires_at=scheduled_at + timedelta(seconds=payload.message.ttl),
        )
        .on_conflict_do_nothing()
        .returning(JalasePushCampaign.id)
    )
    if created is None:
        existing = await session.get(JalasePushCampaign, payload.id)
        if existing is None or existing.actor_id != principal.id or existing.payload != content:
            raise push.invalid()
    else:
        await record(
            session,
            principal,
            "test" if test else "create",
            campaign_id=str(payload.id),
            audience=payload.audience.kind,
        )
    return {"id": payload.id}


class CampaignIn(push.Send):
    proof: StaffSensitiveAction | None = None


@router.post(ADMIN + "/campaigns", status_code=202)
async def send(
    payload: CampaignIn, session: StaffSession, principal: SuperAdminDep
) -> dict[str, UUID]:
    from app.routers.admin import _verify_sensitive_staff_action

    if payload.audience.kind == "all":
        if not payload.confirmed_all or payload.proof is None:
            raise push.invalid()
        await ratelimit.enforce(f"push-broadcast:{principal.id}", 12)
        await _verify_sensitive_staff_action(
            session, principal, payload.proof.current_password, payload.proof.totp_code
        )
    return await enqueue(payload, session, principal)


@router.post(ADMIN + "/test", status_code=202)
async def test_send(
    payload: push.TestSend, session: StaffSession, principal: SuperAdminDep
) -> dict[str, UUID]:
    audience = push.Audience(kind="devices", device_ids=[payload.installation_id])
    if await session.scalar(push.recipients(audience, datetime.now(UTC))) is None:
        raise denied()
    return await enqueue(
        push.Send(id=payload.id, audience=audience, message=payload.message),
        session,
        principal,
        test=True,
    )


@router.post(ADMIN + "/campaigns/{campaign_id}/cancel", status_code=204)
async def cancel(campaign_id: UUID, session: StaffSession, principal: SuperAdminDep) -> Response:
    row = await session.get(JalasePushCampaign, campaign_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "شناسهٔ ارسال را از تاریخچه بررسی کنید.")
    if row.cancelled_at is None:
        row.cancelled_at = datetime.now(UTC)
        await session.execute(
            update(JalasePushDelivery)
            .where(
                JalasePushDelivery.campaign_id == campaign_id,
                JalasePushDelivery.state == "queued",
            )
            .values(state="cancelled")
        )
        await record(session, principal, "cancel", campaign_id=str(campaign_id))
    return Response(status_code=204)


@router.get(ADMIN + "/campaigns")
async def history(
    session: StaffSession,
    _: SuperAdminDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: str = "",
) -> dict[str, Any]:
    model = JalasePushCampaign
    query = select(model)
    if status == "cancelled":
        query = query.where(model.cancelled_at.is_not(None))
    elif status == "scheduled":
        query = query.where(
            model.started_at.is_(None),
            model.cancelled_at.is_(None),
            model.expires_at > datetime.now(UTC),
        )
    rows = (
        await session.scalars(
            query.order_by(model.scheduled_at.desc(), model.id).offset(offset).limit(51)
        )
    ).all()
    counts: dict[UUID, dict[str, int]] = {}
    delivery = JalasePushDelivery
    for campaign, state, count in (
        await session.execute(
            select(delivery.campaign_id, delivery.state, func.count())
            .where(delivery.campaign_id.in_([row.id for row in rows[:50]]))
            .group_by(delivery.campaign_id, delivery.state)
        )
    ).all():
        counts.setdefault(campaign, {})[state] = count
    return {
        "more": len(rows) > 50,
        "items": [
            {
                "id": row.id,
                "title": row.payload["message"]["title"],
                "scheduled_at": row.scheduled_at,
                "started_at": row.started_at,
                "cancelled_at": row.cancelled_at,
                "expires_at": row.expires_at,
                "audience": row.payload["audience"]["kind"],
                "counts": counts.get(row.id, {}),
            }
            for row in rows[:50]
        ],
    }


@router.get(ADMIN + "/devices")
async def devices(
    session: StaffSession,
    _: SuperAdminDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    version: push.Version | None = None,
    channel: push.Channel | None = None,
    organization_id: UUID | None = None,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    audience = push.Audience(
        kind="organization" if organization_id else "user" if user_id else "all",
        organization_id=organization_id,
        user_id=user_id,
        version=version,
        channel=channel,
    )
    model = JalasePushInstallation
    eligible = push.recipients(audience, datetime.now(UTC)).subquery()
    rows = (
        (
            await session.execute(
                select(model.id, model.channel, model.version, model.seen_at, ApiKey.label)
                .join(eligible, eligible.c.id == model.id)
                .outerjoin(ApiKey, (ApiKey.id == model.mobile_key_id) & ApiKey.revoked_at.is_(None))
                .order_by(model.seen_at.desc(), model.id)
                .offset(offset)
                .limit(51)
            )
        )
        .mappings()
        .all()
    )
    return {"more": len(rows) > 50, "items": [dict(row) for row in rows[:50]]}
