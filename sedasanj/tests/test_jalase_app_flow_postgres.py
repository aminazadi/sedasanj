"""Personal Jalase-Negar flows: one meter, personal-only endpoints and deleting a meeting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from plan_helpers import make_org, requires_postgres, scratch  # noqa: F401
from sqlalchemy import select, text

from app import db
from app.errors import ApiError
from app.models import (
    ApiKey,
    CreditReservation,
    Meeting,
    MeetingDocument,
    Tenant,
    User,
)
from app.routers import jalase_negar_app
from app.routers.meetings import create_session
from app.schemas import MeetingSessionIn
from app.services import jalase_accounts

pytestmark = requires_postgres

TABLES = (
    "meeting_documents",
    "meeting_segments",
    "meeting_minutes",
    "meetings",
    "credit_reservations",
    "ledger_entries",
    "credit_grants",
    "tenant_balance_cache",
    "api_keys",
    "audit_events",
    "jalase_earned_achievements",
    "jalase_xp_events",
    "token_grants",
    "subscriptions",
    "users",
)


@pytest.fixture()
async def created(scratch: None) -> AsyncIterator[list[UUID]]:  # noqa: F811
    tenants: list[UUID] = []
    yield tenants
    async with db.session_scope(staff=True) as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        for tenant_id in tenants:
            for table in TABLES:
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def personal(created: list[UUID]) -> tuple[UUID, UUID]:
    async with db.session_scope(staff=True) as session:
        tenant, user = await jalase_accounts.create_personal_account(
            session, mobile="09" + str(uuid4().int)[:9], display_name="سارا", ip="127.0.0.1"
        )
        created.append(tenant.id)
        return tenant.id, user.id


def principal(tenant_id: UUID, user_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=tenant_id, user_id=user_id, id=uuid4(), kind="mobile", role="user"
    )


def session_in() -> MeetingSessionIn:
    return MeetingSessionIn(
        client_meeting_id=uuid4(),
        started_at=datetime.now(UTC),
        sample_rate=16000,
        channels=1,
        app_version="1.0.0",
        input_kind="audio",
    )


async def test_a_personal_account_needs_tokens_not_minutes(created: list[UUID]) -> None:
    """The app shows hours of tokens; the minute ledger must not block a personal account."""
    tenant_id, user_id = await personal(created)
    async with db.session_scope(tenant_id) as session:
        await session.execute(
            text("UPDATE tenant_balance_cache SET seconds = 0 WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    async with db.session_scope(tenant_id) as session:
        out = await create_session(
            session_in(), SimpleNamespace(status_code=200), principal(tenant_id, user_id), session
        )
    assert out.status == "receiving"
    async with db.session_scope(tenant_id) as session:
        reservations = (
            await session.execute(
                select(CreditReservation).where(CreditReservation.tenant_id == tenant_id)
            )
        ).scalars()
        assert list(reservations) == []


async def test_an_organization_key_cannot_use_the_personal_endpoints(
    created: list[UUID],
) -> None:
    org = await make_org()
    created.append(org.tenant_id)
    org_principal = principal(org.tenant_id, org.user_id)
    for call in (
        jalase_negar_app.get_progress,
        jalase_negar_app.get_invite,
        jalase_negar_app.get_usage,
        jalase_negar_app.list_plans,
    ):
        with pytest.raises(ApiError) as refused:
            await call(org_principal)  # type: ignore[arg-type]
        assert refused.value.code == "forbidden"


async def test_deleting_a_meeting_removes_it_and_its_documents(created: list[UUID]) -> None:
    tenant_id, user_id = await personal(created)
    async with db.session_scope(tenant_id) as session:
        meeting = Meeting(
            tenant_id=tenant_id,
            owner_user_id=user_id,
            client_meeting_id=uuid4(),
            status="complete",
            started_at=datetime.now(UTC),
        )
        session.add(meeting)
        await session.flush()
        session.add(
            MeetingDocument(
                tenant_id=tenant_id,
                meeting_id=meeting.id,
                output_type_code="minutes",
                output_type_version=1,
                status="done",
            )
        )
        meeting_id = meeting.id
    await jalase_negar_app.delete_my_meeting(
        meeting_id,
        SimpleNamespace(client=None),
        principal(tenant_id, user_id),  # type: ignore[arg-type]
    )
    async with db.session_scope(tenant_id) as session:
        assert await session.get(Meeting, meeting_id) is None
        assert (
            await session.execute(
                select(MeetingDocument).where(MeetingDocument.meeting_id == meeting_id)
            )
        ).first() is None


async def test_a_deleted_account_leaves_no_active_key(created: list[UUID]) -> None:
    tenant_id, user_id = await personal(created)
    await jalase_accounts.delete_account(tenant_id=tenant_id, user_id=user_id)
    async with db.session_scope(staff=True) as session:
        keys = (
            (await session.execute(select(ApiKey).where(ApiKey.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert all(key.revoked_at is not None for key in keys)
        assert (await session.get(Tenant, tenant_id)).status == "deleted"  # type: ignore[union-attr]
        user = await session.get(User, user_id)
        assert user is not None and user.mobile_number is None
