"""Shared fixtures for the meeting tests: tenants, tokens, WAV bytes, an in-process API client."""

from __future__ import annotations

import hashlib
import io
import shutil
import wave
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from app.services.queue import MemoryQueue

requires_ffprobe = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe missing")

OWNED_TABLES = (
    "speaker_profiles",  # voiceprints go with them (ON DELETE CASCADE)
    "speaker_sync_state",
    "ledger_entries",
    "audit_events",
    "meeting_pairing_codes",
    "api_keys",
)


def wav_bytes(seconds: float = 2.0, *, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Silent PCM16 WAV; fast to build even for tens of seconds."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(seconds * sample_rate) * channels)
    return buffer.getvalue()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class RecordingQueue(MemoryQueue):
    """MemoryQueue that also remembers the job ids it was given."""

    def __init__(self) -> None:
        super().__init__()
        self.job_ids: list[str | None] = []
        self.fail = False

    async def enqueue(
        self,
        queue: str,
        function: str,
        payload: dict[str, Any],
        *,
        defer: timedelta | None = None,
        job_id: str | None = None,
    ) -> None:
        if self.fail:
            raise ConnectionError("redis is down")
        self.job_ids.append(job_id)
        await super().enqueue(queue, function, payload, defer=defer, job_id=job_id)


class Workspace:
    """One tenant with an org_admin, an operator and a funded balance."""

    def __init__(self, tenant_id: UUID, admin_id: UUID, operator_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.admin_id = admin_id
        self.operator_id = operator_id

    def jwt(self, user_id: UUID, role: str) -> dict[str, str]:
        from app.security import create_access_token

        token = create_access_token(subject=user_id, tenant_id=self.tenant_id, role=role)
        return {"Authorization": f"Bearer {token}"}

    @property
    def admin(self) -> dict[str, str]:
        return self.jwt(self.admin_id, "org_admin")

    @property
    def operator(self) -> dict[str, str]:
        return self.jwt(self.operator_id, "operator")


async def make_workspace(*, minutes: int = 120, retention_days: int = 30) -> Workspace:
    from app import db
    from app.models import Tenant, User
    from app.services import billing

    tenant_id = uuid4()
    async with db.session_scope(staff=True) as session:
        tenant = Tenant(
            id=tenant_id,
            name=f"meet-{uuid4().hex[:6]}",
            price_per_minute_toman=2000,
            audio_retention_days=retention_days,
        )
        session.add(tenant)
        await session.flush()
        users = []
        for role, name in (("org_admin", "Admin"), ("operator", "Operator")):
            user = User(
                tenant_id=tenant_id,
                email=f"{uuid4().hex[:8]}@example.com",
                role=role,
                password_hash="x",
                display_name=name,
            )
            session.add(user)
            users.append(user)
        await session.flush()
        if minutes:
            await billing.topup(
                session, tenant=tenant, minutes=minutes, idempotency_key=f"seed:{tenant_id}"
            )
        return Workspace(tenant_id, users[0].id, users[1].id)


async def drop_workspace(workspace: Workspace) -> None:
    from app import db

    tenant = {"t": workspace.tenant_id}
    async with db.session_scope(staff=True) as session:
        await session.execute(
            text(
                "DELETE FROM reservation_allocations WHERE reservation_id IN "
                "(SELECT id FROM credit_reservations WHERE tenant_id = :t)"
            ),
            tenant,
        )
        for table in (
            "credit_reservations",
            "meetings",
            "audio_objects",
            *OWNED_TABLES,
            "credit_grants",
            "tenant_balance_cache",
            "users",
        ):
            await session.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), tenant)
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": workspace.tenant_id})


async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app(), client=("203.0.113.9", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        yield client


async def pair_token(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    """Run the real pairing handshake and return the app's Authorization header."""
    code = await client.post("/v1/meetings/devices/pairing-codes", json={}, headers=headers)
    assert code.status_code == 201, code.text
    paired = await client.post(
        "/v1/meetings/devices/pair",
        json={
            "pairing_code": code.json()["pairing_code"],
            "device_label": "Pixel",
            "app_version": "2.0.0",
            "platform": "android",
        },
    )
    assert paired.status_code == 201, paired.text
    return {"Authorization": f"Bearer {paired.json()['token']}"}
