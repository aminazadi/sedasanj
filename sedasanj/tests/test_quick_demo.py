from __future__ import annotations

import asyncio
import io
import os
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import make_url
from starlette.datastructures import Headers

from app.config import get_settings
from app.db import control_session_scope, dispose_engine, session_scope
from app.main import create_app
from app.models import (
    AudioObject,
    Call,
    CreditGrant,
    Job,
    PhoneOtp,
    PlatformSetting,
    QuickDemoSession,
    StaffUser,
    Subscription,
    Tenant,
    TrialClaim,
    User,
)
from app.security import (
    create_access_token,
    decode_access_token,
    generate_totp_secret,
    hash_password,
)
from app.services import demo_settings, queue, ratelimit, smsir, storage
from app.services.audio import probe_wav_bytes
from app.services.demo_audio import normalize_upload


@pytest.fixture
async def demo_env(monkeypatch, wav_factory):
    url = os.environ.get("QUICK_DEMO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set QUICK_DEMO_TEST_DATABASE_URL to an isolated migrated test database")
    assert (make_url(url).database or "").startswith("quick_demo_test"), (
        "An isolated test database is required"
    )
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("TENANT_DATABASES_ENABLED", "false")
    monkeypatch.setenv("QUEUE_BACKEND", "memory")
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    await dispose_engine()
    memory = storage.MemoryStorage("quick-demo-test")
    storage.set_storage(memory)
    memory_queue = queue.MemoryQueue()
    queue.set_queue(memory_queue)
    ratelimit._memory.clear()
    sent = {}

    async def send(mobile, code, settings=None):
        sent[mobile] = code

    monkeypatch.setattr(smsir, "send_verification", send)
    staff_id = uuid4()
    async with control_session_scope() as session:
        await session.execute(
            delete(PlatformSetting).where(PlatformSetting.key.like("quick_demo.%"))
        )
        session.add(
            StaffUser(
                id=staff_id,
                email=f"test-{staff_id}@example.com",
                password_hash=hash_password("test-only-password"),
                role="super_admin",
            )
        )
    staff_token = create_access_token(
        subject=staff_id, tenant_id=None, role="super_admin", actor="staff"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        staff_headers = {"Authorization": f"Bearer {staff_token}"}
        response = await client.post(
            "/v1/admin/quick-demo/prompt",
            headers=staff_headers,
            files={"file": ("prompt.wav", wav_factory(), "audio/wav")},
        )
        assert response.status_code == 200, response.text
        yield SimpleNamespace(
            client=client,
            sent=sent,
            staff_headers=staff_headers,
            storage=memory,
            queue=memory_queue,
        )
    await dispose_engine()
    storage.set_storage(None)
    queue.set_queue(None)
    get_settings.cache_clear()


def mobile_number() -> str:
    return "09" + f"{secrets.randbelow(1_000_000_000):09d}"


async def verify(env, mobile):
    requested = await env.client.post("/v1/auth/phone/request", json={"mobile": mobile})
    assert requested.status_code == 201, requested.text
    assert "development_code" not in requested.json()
    otp_id = requested.json()["otp_id"]
    result = await env.client.post(
        "/v1/auth/phone/verify", json={"otp_id": otp_id, "code": env.sent[mobile]}
    )
    assert result.status_code == 200, result.text
    return result.json(), otp_id


async def login(env, mobile=None):
    mobile = mobile or mobile_number()
    grant, otp_id = await verify(env, mobile)
    response = await env.client.post(
        "/v1/auth/phone/complete",
        json={
            "verified_token": grant["verified_token"],
            "organization_name": "سازمان تست",
        },
    )
    assert response.status_code == 200, response.text
    pair = response.json()
    claims = decode_access_token(pair["access_token"])
    return SimpleNamespace(
        mobile=mobile,
        otp_id=otp_id,
        grant=grant,
        pair=pair,
        tenant_id=UUID(claims["tenant_id"]),
        user_id=UUID(claims["sub"]),
        headers={"Authorization": f"Bearer {pair['access_token']}"},
    )


async def new_session(env, account):
    response = await env.client.post("/v1/quick-demo/sessions", headers=account.headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_phone_signup_activates_demo_and_voicemail_enters_asr_queue(demo_env, wav_factory):
    env = demo_env
    account = await login(env)
    async with control_session_scope() as session:
        subscription = (
            await session.execute(
                select(Subscription).where(Subscription.tenant_id == account.tenant_id)
            )
        ).scalar_one()
        assert subscription.status == "trialing"
        assert (
            await session.execute(
                select(func.count())
                .select_from(TrialClaim)
                .where(TrialClaim.mobile == account.mobile)
            )
        ).scalar_one() == 1
        assert (
            await session.execute(
                select(func.sum(CreditGrant.total_seconds)).where(
                    CreditGrant.tenant_id == account.tenant_id
                )
            )
        ).scalar_one() == 1200
    demo = await new_session(env, account)
    audio = wav_factory(seconds=1, sample_rate=44100)
    for _ in range(2):
        response = await env.client.post(
            "/v1/quick-demo/recording/upload",
            data={"token": demo["token"]},
            files={"file": ("recording.wav", audio, "audio/wav")},
        )
        assert response.status_code == 200, response.text
    async with session_scope(account.tenant_id) as session:
        call = (await session.execute(select(Call))).scalar_one()
        assert call.call_type == "voicemail"
        assert call.source == "browser_quick_demo"
        assert call.caller_number == account.mobile
        obj = await session.get(AudioObject, call.audio_id)
        assert (obj.sample_rate, obj.channels) == (16000, 1)
        job = (await session.execute(select(Job).where(Job.call_id == call.id))).scalar_one()
        assert job.kind == "asr" and job.status == "queued"
        assert (await session.execute(select(func.count()).select_from(PhoneOtp))).scalar_one() == 0
    assert len(env.queue.jobs) == 1
    status = await env.client.get(
        f"/v1/quick-demo/sessions/{demo['session_id']}", headers=account.headers
    )
    assert status.json()["call_id"] == str(call.id)
    scoped = await env.client.post("/v1/quick-demo/recording/status", json={"token": demo["token"]})
    assert scoped.json()["completed"] is True
    assert "call_id" not in scoped.json()
    denied = await env.client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {demo['token']}"}
    )
    assert denied.status_code == 401


async def test_failed_otp_attempts_persist_and_success_is_one_use(demo_env):
    env = demo_env
    mobile = mobile_number()
    response = await env.client.post("/v1/auth/phone/request", json={"mobile": mobile})
    otp_id = response.json()["otp_id"]
    wrong = "000000" if env.sent[mobile] != "000000" else "111111"
    for _ in range(5):
        rejected = await env.client.post(
            "/v1/auth/phone/verify", json={"otp_id": otp_id, "code": wrong}
        )
        assert rejected.status_code == 401
    correct = await env.client.post(
        "/v1/auth/phone/verify", json={"otp_id": otp_id, "code": env.sent[mobile]}
    )
    assert correct.status_code == 401
    async with control_session_scope() as session:
        assert (await session.get(PhoneOtp, UUID(otp_id))).attempts == 5
    grant, _ = await verify(env, mobile_number())
    payload = {"verified_token": grant["verified_token"], "organization_name": "سازمان همزمان"}
    results = await asyncio.gather(
        *(env.client.post("/v1/auth/phone/complete", json=payload) for _ in range(2))
    )
    assert sorted(response.status_code for response in results) == [200, 401]


async def test_existing_mobile_logs_into_same_organization_without_new_trial(demo_env):
    env = demo_env
    first = await login(env)
    async with control_session_scope() as session:
        await session.execute(
            update(PhoneOtp)
            .where(PhoneOtp.mobile == first.mobile)
            .values(created_at=datetime.now(UTC) - timedelta(minutes=2))
        )
    second = await login(env, first.mobile)
    assert second.user_id == first.user_id
    assert second.tenant_id == first.tenant_id
    async with control_session_scope() as session:
        assert (
            await session.execute(
                select(func.count())
                .select_from(TrialClaim)
                .where(TrialClaim.mobile == first.mobile)
            )
        ).scalar_one() == 1


async def test_rotated_and_expired_qr_are_rejected(demo_env):
    env = demo_env
    account = await login(env)
    first = await new_session(env, account)
    second = await new_session(env, account)
    denied = await env.client.post(
        "/v1/quick-demo/recording/status", json={"token": first["token"]}
    )
    assert denied.status_code == 401
    async with control_session_scope() as session:
        await session.execute(
            update(QuickDemoSession)
            .where(QuickDemoSession.id == UUID(second["session_id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    expired = await env.client.post(
        "/v1/quick-demo/recording/status", json={"token": second["token"]}
    )
    assert expired.status_code == 401


async def test_quota_and_upload_validation_are_enforced_server_side(demo_env, wav_factory):
    env = demo_env
    account = await login(env)
    response = await env.client.patch(
        "/v1/admin/quick-demo/settings",
        headers=env.staff_headers,
        json={"max_duration_seconds": 10, "max_calls_per_mobile": 1},
    )
    assert response.status_code == 200
    demo = await new_session(env, account)
    for data, media in [(b"invalid audio", "audio/webm"), (wav_factory(seconds=12), "audio/wav")]:
        rejected = await env.client.post(
            "/v1/quick-demo/recording/upload",
            data={"token": demo["token"]},
            files={"file": ("recording", data, media)},
        )
        assert rejected.status_code == 415, rejected.text
    accepted = await env.client.post(
        "/v1/quick-demo/recording/upload",
        data={"token": demo["token"]},
        files={"file": ("recording.wav", wav_factory(), "audio/wav")},
    )
    assert accepted.status_code == 200, accepted.text
    blocked = await env.client.post("/v1/quick-demo/sessions", headers=account.headers)
    assert blocked.status_code == 402


async def test_sms_admin_configuration_is_encrypted_and_not_public(demo_env):
    env = demo_env
    response = await env.client.patch(
        "/v1/admin/quick-demo/settings",
        headers=env.staff_headers,
        json={
            "smsir_api_key": "test-private-key",
            "smsir_template_id": 234,
            "smsir_code_parameter": "Code",
        },
    )
    assert response.status_code == 200, response.text
    assert "smsir_api_key" not in response.json()
    async with control_session_scope() as session:
        row = await session.get(PlatformSetting, "quick_demo.smsir_api_key")
        assert row.value.startswith("fernet:v1:")
        assert (await demo_settings.load(session)).smsir_api_key == "test-private-key"
    public = await env.client.get("/v1/quick-demo/config")
    assert "smsir_api_key" not in public.text
    rejected = await env.client.patch(
        "/v1/admin/quick-demo/settings",
        headers=env.staff_headers,
        json={"smsir_base_url": "http://example.com"},
    )
    assert rejected.status_code == 422


async def test_resend_revokes_the_previous_verified_grant(demo_env):
    env = demo_env
    mobile = mobile_number()
    grant, otp_id = await verify(env, mobile)
    async with control_session_scope() as session:
        row = await session.get(PhoneOtp, UUID(otp_id))
        row.created_at = datetime.now(UTC) - timedelta(minutes=2)
    requested = await env.client.post("/v1/auth/phone/request", json={"mobile": mobile})
    assert requested.status_code == 201
    rejected = await env.client.post(
        "/v1/auth/phone/complete",
        json={
            "verified_token": grant["verified_token"],
            "organization_name": "سازمان تست",
        },
    )
    assert rejected.status_code == 401


async def test_existing_multiple_organizations_require_selection_and_preserve_totp(demo_env):
    env = demo_env
    account = await login(env)
    second_user_id = uuid4()
    async with control_session_scope() as session:
        await session.execute(
            update(PhoneOtp)
            .where(PhoneOtp.mobile == account.mobile)
            .values(created_at=datetime.now(UTC) - timedelta(minutes=2))
        )
        user = await session.get(User, account.user_id)
        user.totp_secret = generate_totp_secret()
        other = Tenant(name="سازمان دوم", status="active", price_per_minute_toman=2000)
        session.add(other)
        await session.flush()
        session.add(
            User(
                id=second_user_id,
                tenant_id=other.id,
                email=f"test-{uuid4()}@example.com",
                password_hash=hash_password("test-only-password"),
                role="org_admin",
                mobile_number="+98" + account.mobile[1:],
            )
        )
    grant, _ = await verify(env, account.mobile)
    assert len(grant["accounts"]) == 2
    assert grant["accounts"][0]["requires_totp"] is True
    missing_selection = await env.client.post(
        "/v1/auth/phone/complete", json={"verified_token": grant["verified_token"]}
    )
    assert missing_selection.status_code == 422
    missing_totp = await env.client.post(
        "/v1/auth/phone/complete",
        json={"verified_token": grant["verified_token"], "user_id": str(account.user_id)},
    )
    assert missing_totp.status_code == 401
    selected = await env.client.post(
        "/v1/auth/phone/complete",
        json={"verified_token": grant["verified_token"], "user_id": str(second_user_id)},
    )
    assert selected.status_code == 200
    assert decode_access_token(selected.json()["access_token"])["sub"] == str(second_user_id)


async def test_failed_storage_upload_can_be_retried_without_duplicating_an_accepted_call(
    demo_env, wav_factory, monkeypatch
):
    env = demo_env
    account = await login(env)
    demo = await new_session(env, account)
    original = env.storage.put_path
    failures = []

    async def fail_once(key, path, content_type="audio/wav"):
        if not failures:
            failures.append(True)
            raise RuntimeError("test storage outage")
        await original(key, path, content_type)

    monkeypatch.setattr(env.storage, "put_path", fail_once)
    for expected in (500, 200, 200):
        response = await env.client.post(
            "/v1/quick-demo/recording/upload",
            data={"token": demo["token"]},
            files={"file": ("recording.wav", wav_factory(), "audio/wav")},
        )
        assert response.status_code == expected, response.text
    async with session_scope(account.tenant_id) as session:
        calls = (await session.execute(select(Call))).scalars().all()
        assert sum(call.audio_id is not None for call in calls) == 1
    assert len(env.queue.jobs) == 1


async def test_expired_demo_is_not_reactivated_by_phone_login(demo_env):
    env = demo_env
    account = await login(env)
    async with control_session_scope() as session:
        await session.execute(
            update(Subscription)
            .where(Subscription.tenant_id == account.tenant_id)
            .values(period_end=datetime.now(UTC) - timedelta(seconds=1))
        )
    rejected = await env.client.post("/v1/quick-demo/sessions", headers=account.headers)
    assert rejected.status_code == 402


async def test_demo_session_is_only_visible_to_its_owner(demo_env):
    env = demo_env
    first = await login(env)
    demo = await new_session(env, first)
    other = await login(env)
    rejected = await env.client.get(
        f"/v1/quick-demo/sessions/{demo['session_id']}", headers=other.headers
    )
    assert rejected.status_code == 404


async def test_total_minutes_limit_rejects_recordings_that_exceed_remaining_budget(
    demo_env, wav_factory
):
    env = demo_env
    account = await login(env)
    await env.client.patch(
        "/v1/admin/quick-demo/settings",
        headers=env.staff_headers,
        json={"max_total_minutes": 1, "max_duration_seconds": 120},
    )
    demo = await new_session(env, account)
    assert demo["max_duration_seconds"] == 60
    response = await env.client.post(
        "/v1/quick-demo/recording/upload",
        data={"token": demo["token"]},
        files={"file": ("recording.wav", wav_factory(seconds=59), "audio/wav")},
    )
    assert response.status_code == 200, response.text
    remaining = await new_session(env, account)
    assert remaining["max_duration_seconds"] == 1


@pytest.mark.parametrize(
    "extension,codec,media", [("webm", "libopus", "audio/webm"), ("m4a", "aac", "audio/mp4")]
)
async def test_mobile_recording_formats_convert_to_pipeline_wav(
    tmp_path, wav_factory, extension, codec, media
):
    source = tmp_path / "source.wav"
    source.write_bytes(wav_factory(seconds=1, sample_rate=44100))
    encoded = tmp_path / f"browser.{extension}"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-y", "-i", str(source), "-c:a", codec, str(encoded)
    )
    assert await process.wait() == 0
    file = UploadFile(
        io.BytesIO(encoded.read_bytes()),
        filename=encoded.name,
        headers=Headers({"content-type": media}),
    )
    normalized, probe = await normalize_upload(file, tmp_path, 10)
    assert (probe.channels, probe.sample_rate, probe.codec) == (1, 16000, "pcm_s16le")
    assert 900 <= (await probe_wav_bytes(normalized.read_bytes())).duration_ms <= 1100
