"""Durable push scheduling and bounded delivery batches."""

import math
import time
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from uuid import UUID

import httpx
from sqlalchemy import insert, literal, select, update

from app.db import session_scope
from app.errors import ApiError
from app.models import JalasePushCampaign as Campaign
from app.models import JalasePushDelivery as Delivery
from app.models import JalasePushInstallation as Installation
from app.services import jalase_push as push
from app.services.platform_secrets import decrypt_secret

DeliveryKey = tuple[UUID, UUID]


async def start_campaigns(now: datetime) -> None:
    async with session_scope(staff=True) as session:
        await session.execute(
            update(Delivery)
            .where(Delivery.state == "sending", Delivery.next_at <= now)
            .values(state="unknown", error="attempt_interrupted")
        )
        await session.execute(
            update(Delivery)
            .where(
                Delivery.state == "queued",
                Delivery.campaign_id.in_(select(Campaign.id).where(Campaign.expires_at <= now)),
            )
            .values(state="failed", error="expired")
        )
        config = await push.settings(session)
        if not config or not config.enabled:
            return
        campaigns = (
            await session.scalars(
                select(Campaign)
                .where(
                    Campaign.started_at.is_(None),
                    Campaign.cancelled_at.is_(None),
                    Campaign.scheduled_at <= now,
                    Campaign.expires_at > now,
                )
                .order_by(Campaign.scheduled_at, Campaign.id)
                .limit(4)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for campaign in campaigns:
            audience = push.Audience.model_validate(campaign.payload["audience"])
            matching = push.recipients(audience, now).with_only_columns(
                literal(campaign.id), Installation.id, literal("queued"), literal(now), literal(0)
            )
            await session.execute(
                insert(Delivery).from_select(
                    ["campaign_id", "installation_id", "state", "next_at", "attempts"], matching
                )
            )
            campaign.started_at = now


async def claim() -> DeliveryKey | None:
    now = datetime.now(UTC)
    async with session_scope(staff=True) as session:
        delivery = await session.scalar(
            select(Delivery)
            .join(Campaign)
            .where(
                Delivery.state == "queued",
                Delivery.next_at <= now,
                Campaign.cancelled_at.is_(None),
                Campaign.expires_at > now,
            )
            .order_by(Delivery.next_at, Delivery.campaign_id, Delivery.installation_id)
            .limit(1)
            .with_for_update(of=Delivery, skip_locked=True)
        )
        if delivery is None:
            return None
        delivery.state = "sending"
        delivery.attempts += 1
        delivery.next_at = now + timedelta(minutes=2)
        return delivery.campaign_id, delivery.installation_id


def provider_error(response: httpx.Response) -> str:
    try:
        for detail in response.json()["error"]["details"]:
            if (
                detail.get("@type") == "type.googleapis.com/google.firebase.fcm.v1.FcmError"
                and detail.get("errorCode") == "UNREGISTERED"
                and response.status_code == 404
            ):
                return "unregistered"
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    return f"fcm_{response.status_code}"


def retry_seconds(attempts: int, header: str | None) -> int:
    delay = 60 << min(max(attempts - 1, 0), 6)
    if header:
        try:
            retry_after = int(header)
        except ValueError:
            try:
                retry_after = math.ceil(
                    (parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds()
                )
            except (ValueError, TypeError, OverflowError):
                return delay
        return max(delay, retry_after)
    return delay


def retry(delivery: Delivery, campaign: Campaign, header: str | None = None) -> None:
    delay = min(retry_seconds(delivery.attempts, header), 2419200)
    delivery.next_at = datetime.now(UTC) + timedelta(seconds=delay)
    delivery.state = "queued" if delivery.next_at < campaign.expires_at else "failed"


async def deliver(key: DeliveryKey, firebase: push.Firebase) -> None:
    async with session_scope(staff=True) as session:
        campaign = await session.get(Campaign, key[0], with_for_update={"read": True})
        delivery = await session.get(Delivery, key, with_for_update=True)
        if campaign is None or delivery is None or delivery.state != "sending":
            return
        now = datetime.now(UTC)
        if campaign.cancelled_at is not None:
            delivery.state = "cancelled"
            return
        if campaign.expires_at <= now:
            delivery.state, delivery.error = "failed", "expired"
            return
        audience = push.Audience.model_validate(campaign.payload["audience"])
        installation = await session.scalar(
            push.recipients(audience, now)
            .where(Installation.id == key[1])
            .with_for_update(of=Installation)
        )
        if installation is None:
            delivery.state, delivery.error = "failed", "ineligible"
            return
        config = await push.settings(session)
        if not config or not config.enabled or config.project != firebase.project:
            delivery.error = "firebase_disabled"
            retry(delivery, campaign)
            return
        message = push.Message.model_validate(campaign.payload["message"])
        ttl = max(1, math.ceil((campaign.expires_at - now).total_seconds()))
        payload = push.envelope(message, campaign.id, ttl, targeted=audience.kind != "all")
        try:
            payload["token"] = decrypt_secret(installation.token)
        except RuntimeError:
            delivery.state, delivery.error = "failed", "token_unavailable"
            return
        try:
            response = await firebase.send(payload)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            delivery.error = "firebase_connect"
            retry(delivery, campaign)
            return
        except httpx.TransportError:
            delivery.state, delivery.error = "unknown", "firebase_response_lost"
            return
        if response.is_success:
            delivery.state, delivery.error = "accepted", None
            return
        delivery.error = provider_error(response)
        if delivery.error == "unregistered":
            installation.enabled = False
            installation.invalidated = True
        if response.status_code in (429, 500, 503):
            retry(delivery, campaign, response.headers.get("Retry-After"))
        else:
            delivery.state = "failed"


async def run_batch() -> int:
    await start_campaigns(datetime.now(UTC))
    async with session_scope(staff=True) as session:
        config = await push.settings(session)
        if not config or not config.enabled:
            return 0
        if not await session.scalar(
            select(literal(True))
            .select_from(Delivery)
            .where(Delivery.state == "queued", Delivery.next_at <= datetime.now(UTC))
            .limit(1)
        ):
            return 0
    async with httpx.AsyncClient(timeout=8) as client:
        try:
            firebase = push.Firebase(client, config)
            await firebase.authenticate()
        except (ApiError, ValueError, RuntimeError, httpx.HTTPError):
            # No FCM send was attempted. Keep queued work available for repaired credentials.
            return 0
        count = 0
        deadline = time.monotonic() + 35
        while count < 100 and time.monotonic() < deadline:
            key = await claim()
            if key is None:
                break
            await deliver(key, firebase)
            count += 1
        return count
