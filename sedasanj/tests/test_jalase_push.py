"""Push contract and optional integration coverage against a migrated scratch database."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.deps import Principal, current_staff, public_session, staff_session
from app.errors import ApiError, install_error_handlers
from app.models import (
    ApiKey,
    JalasePushCampaign,
    JalasePushDelivery,
    JalasePushInstallation,
    JalasePushSettings,
    Tenant,
    User,
)
from app.routers import admin
from app.routers import jalase_push as router
from app.services import jalase_push as push
from app.services import jalase_push_worker as worker

VISIBLE = {"kind": "notification", "title": "جلسه", "body": "یک اعلان آزمایشی"}


@pytest.mark.parametrize(
    "changes",
    [
        {"title": ""},
        {"image": "http://example.com/photo.png"},
        {"destination": "https://example.com"},
        {"data": {"field": "unexpected"}},
        {"kind": "combined", "data": {"text": "گ" * 3000}},
        {"kind": "data", "priority": "high", "data": {"event": "one"}},
    ],
)
def test_rejects_invalid_messages(changes: dict[str, Any]) -> None:
    with pytest.raises((ValueError, ApiError)):
        push.Message.model_validate({**VISIBLE, **changes})


def test_wire_payload_and_provider_status() -> None:
    message = push.Message.model_validate(
        {
            **VISIBLE,
            "kind": "combined",
            "data": {"nested": {"enabled": True}},
        }
    )
    campaign = uuid4()
    full = push.envelope(message, campaign, 90)
    assert json.loads(full["data"]["payload"])["data"] == {"nested": {"enabled": True}}
    private = push.envelope(message, campaign, 90, targeted=True)
    assert private["data"] == {"campaign_id": str(campaign)}
    assert private["android"]["ttl"] == "90s"
    assert worker.retry_seconds(1, "120") == 120
    assert worker.retry_seconds(2, "5") == 120
    assert (
        worker.provider_error(
            httpx.Response(
                404,
                json={
                    "error": {
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                                "errorCode": "UNREGISTERED",
                            }
                        ]
                    }
                },
            )
        )
        == "unregistered"
    )
    assert worker.provider_error(httpx.Response(404)) == "fcm_404"


@pytest.fixture
async def lab(monkeypatch: pytest.MonkeyPatch):
    dsn = os.environ.get("JALASE_PUSH_TEST_DSN")
    if not dsn:
        pytest.skip("Set JALASE_PUSH_TEST_DSN to a migrated disposable PostgreSQL database.")
    assert "test" in (make_url(dsn).database or "")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(get_settings(), "platform_secrets_key", Fernet.generate_key().decode())

    @asynccontextmanager
    async def transaction(*, staff: bool = True) -> AsyncIterator[AsyncSession]:
        async with maker.begin() as session:
            await session.execute(text("SET LOCAL app.staff = 'on'"))
            yield session

    async def endpoint_session() -> AsyncIterator[AsyncSession]:
        async with transaction() as session:
            yield session

    async def allow(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(router.ratelimit, "enforce", allow)
    monkeypatch.setattr(worker, "session_scope", transaction)
    monkeypatch.setattr(admin, "_verify_sensitive_staff_action", allow)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router.router)
    role = ["super_admin"]
    actor = uuid4()
    mobile_keys: dict[str, ApiKey] = {}

    def principal() -> Principal:
        return Principal(kind="staff", id=actor, tenant_id=None, role=role[0])

    async def mobile(request: Any, *, x_api_key: str) -> Principal:
        key = mobile_keys[x_api_key]
        async with transaction() as session:
            row = await session.get(ApiKey, key.id)
            if row is None or row.revoked_at is not None:
                raise ApiError("unauthorized", "Pair the app again.")
        return Principal(
            kind="api_key",
            id=key.id,
            tenant_id=key.tenant_id,
            role="agent",
            user_id=key.user_id,
            key_kind="mobile",
            scopes=frozenset({"meetings:write"}),
        )

    app.dependency_overrides[current_staff] = principal
    app.dependency_overrides[public_session] = endpoint_session
    app.dependency_overrides[staff_session] = endpoint_session
    monkeypatch.setattr(router, "current_api_key", mobile)

    async with transaction() as session:
        for model in (
            JalasePushDelivery,
            JalasePushCampaign,
            JalasePushInstallation,
            JalasePushSettings,
        ):
            await session.execute(delete(model))
        for label in ("mobile-one", "mobile-two"):
            tenant = Tenant(name=label, price_per_minute_toman=0)
            session.add(tenant)
            await session.flush()
            user = User(
                tenant_id=tenant.id,
                email=f"{uuid4()}@example.test",
                role="org_admin",
                password_hash="test",
            )
            session.add(user)
            await session.flush()
            key = ApiKey(
                tenant_id=tenant.id,
                user_id=user.id,
                kind="mobile",
                key_hash=str(uuid4()),
                key_prefix=str(uuid4())[:8],
                scopes=["meetings:write"],
            )
            session.add(key)
            await session.flush()
            mobile_keys[label] = key
        await session.execute(
            text("INSERT INTO jalase_push_settings VALUES (1, true, 'push-test', 'placeholder')")
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test.invalid"
    ) as client:
        yield client, transaction, role, mobile_keys
    await engine.dispose()


async def register(
    client: httpx.AsyncClient, *, mobile: str | None = None
) -> tuple[UUID, dict[str, str], dict[str, Any]]:
    installation = uuid4()
    headers = {"X-Installation-Secret": f"{uuid4()}-{uuid4()}"}
    if mobile:
        headers["X-Api-Key"] = mobile
    content = {"token": str(uuid4()), "channel": "direct", "version": "1.2.0", "enabled": True}
    result = await client.put(f"{router.PUBLIC}/{installation}", json=content, headers=headers)
    assert result.status_code == 204, result.text
    return installation, headers, content


class FakeFirebase:
    project = "push-test"

    def __init__(self, result: int | Exception = 200) -> None:
        self.result = result
        self.messages: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> httpx.Response:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return httpx.Response(self.result, headers={"Retry-After": "80"})


@pytest.mark.asyncio
async def test_registration_targeting_and_revocation(lab) -> None:
    client, transaction, role, keys = lab
    role[0] = "support"
    assert (await client.get(router.ADMIN + "/devices")).status_code == 403
    role[0] = "super_admin"
    anonymous, headers, original = await register(client)
    one, one_headers, _ = await register(client, mobile="mobile-one")
    await register(client, mobile="mobile-two")
    revised = {**original, "token": str(uuid4())}
    other_headers = {"X-Installation-Secret": "f" * 64}
    assert (
        await client.put(f"{router.PUBLIC}/{anonymous}", json=revised, headers=other_headers)
    ).status_code == 403
    assert (
        await client.put(f"{router.PUBLIC}/{anonymous}", json=revised, headers=headers)
    ).status_code == 204
    async with transaction() as session:
        device = await session.get(JalasePushInstallation, anonymous)
        assert device.token.startswith("fernet:v1:")
        assert revised["token"] not in device.token
        assert device.secret_hash != headers["X-Installation-Secret"]
    listed = await client.get(router.ADMIN + "/devices")
    assert len(listed.json()["items"]) == 3
    assert revised["token"] not in listed.text and "token_hash" not in listed.text

    campaign = uuid4()
    content = {
        "id": str(campaign),
        "message": VISIBLE,
        "audience": {
            "kind": "organization",
            "organization_id": str(keys["mobile-one"].tenant_id),
        },
    }
    preview = await client.post(router.ADMIN + "/preview", json=content)
    assert preview.json() == {"count": 1}
    assert (await client.post(router.ADMIN + "/campaigns", json=content)).status_code == 202
    assert (await client.post(router.ADMIN + "/campaigns", json=content)).status_code == 202
    assert (
        await client.post(
            router.ADMIN + "/campaigns",
            json={
                **content,
                "audience": {"kind": "all"},
            },
        )
    ).status_code == 422
    await worker.start_campaigns(datetime.now(UTC))
    claims = await asyncio.gather(worker.claim(), worker.claim())
    assert set(claims) == {(campaign, one), None}
    firebase = FakeFirebase()
    await worker.deliver((campaign, one), firebase)
    assert firebase.messages[0]["data"] == {"campaign_id": str(campaign)}
    path = f"{router.PUBLIC}/{one}/messages/{campaign}"
    assert (await client.get(path, headers=one_headers)).json()["body"] == VISIBLE["body"]
    assert (
        await client.get(
            path,
            headers={
                **one_headers,
                "X-Api-Key": "mobile-two",
            },
        )
    ).status_code == 403
    async with transaction() as session:
        key = await session.get(ApiKey, keys["mobile-one"].id)
        key.revoked_at = datetime.now(UTC)
    assert (await client.get(path, headers=one_headers)).status_code == 401
    assert (await client.post(router.ADMIN + "/preview", json=content)).json() == {"count": 0}
    assert (
        await client.post(
            router.ADMIN + "/preview",
            json={
                **content,
                "audience": {"kind": "all"},
            },
        )
    ).json() == {"count": 3}


@pytest.mark.asyncio
async def test_schedule_retry_cancel_and_worker_recovery(lab) -> None:
    client, transaction, _, _ = lab
    device, _, _ = await register(client)
    start = datetime.now(UTC)
    campaign = uuid4()
    content = {
        "id": str(campaign),
        "message": {**VISIBLE, "ttl": 600},
        "audience": {"kind": "devices", "device_ids": [str(device)]},
        "scheduled_at": (start + timedelta(minutes=1)).isoformat(),
    }
    assert (await client.post(router.ADMIN + "/campaigns", json=content)).status_code == 202
    await worker.start_campaigns(start)
    assert await worker.claim() is None
    async with transaction() as session:
        row = await session.get(JalasePushCampaign, campaign)
        row.scheduled_at = start - timedelta(seconds=1)
    await worker.start_campaigns(datetime.now(UTC))
    key = await worker.claim()
    assert key == (campaign, device)
    before = datetime.now(UTC)
    await worker.deliver(key, FakeFirebase(429))
    async with transaction() as session:
        row = await session.get(JalasePushDelivery, key)
        assert row.state == "queued" and row.next_at >= before + timedelta(seconds=80)
        row.next_at = start
    assert await worker.claim() == key
    await worker.deliver(key, FakeFirebase(httpx.ReadTimeout("response lost")))
    assert await worker.claim() is None
    assert (await client.get(router.ADMIN + "/campaigns")).json()["items"][0]["counts"] == {
        "unknown": 1,
    }

    for cancelled in (True, False):
        trial = uuid4()
        assert (
            await client.post(
                router.ADMIN + "/test",
                json={
                    "id": str(trial),
                    "installation_id": str(device),
                    "message": VISIBLE,
                },
            )
        ).status_code == 202
        await worker.start_campaigns(datetime.now(UTC))
        key = await worker.claim()
        assert key == (trial, device)
        if cancelled:
            assert (
                await client.post(router.ADMIN + f"/campaigns/{trial}/cancel")
            ).status_code == 204
            firebase = FakeFirebase()
            await worker.deliver(key, firebase)
            assert not firebase.messages
        else:
            await worker.start_campaigns(datetime.now(UTC) + timedelta(minutes=3))
        async with transaction() as session:
            row = await session.scalar(
                select(JalasePushDelivery).where(JalasePushDelivery.campaign_id == trial)
            )
            assert row.state == ("cancelled" if cancelled else "unknown")


@pytest.mark.asyncio
async def test_invalidated_token_needs_rotation(lab) -> None:
    client, transaction, _, _ = lab
    device, headers, registration = await register(client)
    trial = uuid4()
    result = await client.post(
        router.ADMIN + "/test",
        json={
            "id": str(trial),
            "installation_id": str(device),
            "message": VISIBLE,
        },
    )
    assert result.status_code == 202
    await worker.start_campaigns(datetime.now(UTC))
    assert await worker.claim() == (trial, device)

    class InvalidToken(FakeFirebase):
        async def send(self, message: dict[str, Any]) -> httpx.Response:
            return httpx.Response(
                404,
                json={
                    "error": {
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                                "errorCode": "UNREGISTERED",
                            }
                        ]
                    }
                },
            )

    await worker.deliver((trial, device), InvalidToken())
    async with transaction() as session:
        row = await session.get(JalasePushInstallation, device)
        assert row.invalidated and not row.enabled
    path = f"{router.PUBLIC}/{device}"
    result = await client.put(path, json=registration, headers=headers)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "jalase_push_token_expired"
    registration["token"] = str(uuid4())
    assert (await client.put(path, json=registration, headers=headers)).status_code == 204
    assert (await client.get(router.ADMIN + "/devices")).json()["items"][0]["id"] == str(device)
