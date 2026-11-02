"""Block-based meeting billing: reserve per block, settle once, release on cancel."""

from __future__ import annotations

from uuid import uuid4

import pytest
from meeting_helpers import drop_workspace, make_workspace
from plan_helpers import requires_postgres, scratch  # noqa: F401  (scratch is a fixture)
from sqlalchemy import func, select

from app import db
from app.errors import ApiError
from app.models import CreditReservation, LedgerEntry, Meeting, Tenant
from app.services import billing
from app.services.billing import billable_seconds


async def test_reserve_needs_exactly_one_target() -> None:
    tenant = Tenant(id=uuid4(), name="t", price_per_minute_toman=1)
    with pytest.raises(ValueError, match="exactly one"):
        await billing.reserve(None, tenant=tenant, duration_ms=1000)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exactly one"):
        await billing.reserve(
            None,
            tenant=tenant,
            call_id=uuid4(),
            meeting_id=uuid4(),
            duration_ms=1000,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="call_id or meeting_id"):
        await billing.settle(None, tenant_id=uuid4(), actual_duration_ms=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="call_id or meeting_id"):
        await billing.release(None, tenant_id=uuid4())  # type: ignore[arg-type]


@pytest.fixture()
async def funded(scratch):  # noqa: F811
    workspace = await make_workspace(minutes=60)  # 3600 s
    try:
        yield workspace
    finally:
        await drop_workspace(workspace)


async def _new_meeting(workspace) -> tuple[Meeting, Tenant]:
    from datetime import UTC, datetime

    async with db.session_scope(workspace.tenant_id) as session:
        meeting = Meeting(
            tenant_id=workspace.tenant_id,
            owner_user_id=workspace.admin_id,
            client_meeting_id=uuid4(),
            started_at=datetime.now(UTC),
        )
        session.add(meeting)
        await session.flush()
        tenant = await session.get(Tenant, workspace.tenant_id)
        assert tenant is not None
        return meeting, tenant


async def _balance(session, tenant_id) -> int:
    return (await billing.get_balance(session, tenant_id)).seconds


@requires_postgres
async def test_blocks_are_separate_idempotent_reservations(funded) -> None:
    meeting, tenant = await _new_meeting(funded)
    async with db.session_scope(funded.tenant_id) as session:
        first = await billing.reserve(
            session, tenant=tenant, meeting_id=meeting.id, block=0, duration_ms=300_000
        )
        again = await billing.reserve(
            session, tenant=tenant, meeting_id=meeting.id, block=0, duration_ms=300_000
        )
        second = await billing.reserve(
            session, tenant=tenant, meeting_id=meeting.id, block=1, duration_ms=300_000
        )
        assert again.id == first.id and second.id != first.id
        assert first.meeting_id == meeting.id and first.call_id is None
        assert await _balance(session, funded.tenant_id) == 3600 - 600
        keys = (
            await session.execute(
                select(LedgerEntry.idempotency_key, LedgerEntry.meeting_id)
                .where(LedgerEntry.tenant_id == funded.tenant_id, LedgerEntry.kind == "reservation")
                .order_by(LedgerEntry.idempotency_key)
            )
        ).all()
    assert keys == [
        (f"meeting-reserve:{meeting.id}:0", meeting.id),
        (f"meeting-reserve:{meeting.id}:1", meeting.id),
    ]


@requires_postgres
async def test_settle_charges_the_recorded_length_and_returns_the_rest(funded) -> None:
    meeting, tenant = await _new_meeting(funded)
    async with db.session_scope(funded.tenant_id) as session:
        for block in range(2):
            await billing.reserve(
                session, tenant=tenant, meeting_id=meeting.id, block=block, duration_ms=300_000
            )
    async with db.session_scope(funded.tenant_id) as session:
        billed = await billing.settle(
            session, tenant_id=funded.tenant_id, meeting_id=meeting.id, actual_duration_ms=400_000
        )
        assert billed == 400
        assert await _balance(session, funded.tenant_id) == 3600 - 400
    async with db.session_scope(funded.tenant_id) as session:
        again = await billing.settle(
            session, tenant_id=funded.tenant_id, meeting_id=meeting.id, actual_duration_ms=400_000
        )
        assert again == 400
        assert await _balance(session, funded.tenant_id) == 3600 - 400
        statuses = set(
            (
                await session.execute(
                    select(CreditReservation.status).where(
                        CreditReservation.meeting_id == meeting.id
                    )
                )
            ).scalars()
        )
        assert statuses == {"settled"}
        # A later cancel or delete must not give back what was charged.
        await billing.release(session, tenant_id=funded.tenant_id, meeting_id=meeting.id)
        assert await _balance(session, funded.tenant_id) == 3600 - 400


@requires_postgres
async def test_settle_never_charges_less_than_the_minimum_and_can_top_up(funded) -> None:
    meeting, tenant = await _new_meeting(funded)
    async with db.session_scope(funded.tenant_id) as session:
        await billing.reserve(
            session, tenant=tenant, meeting_id=meeting.id, block=0, duration_ms=60_000
        )
    async with db.session_scope(funded.tenant_id) as session:
        assert await billing.settle(
            session, tenant_id=funded.tenant_id, meeting_id=meeting.id, actual_duration_ms=1000
        ) == billable_seconds(1000)
        assert await _balance(session, funded.tenant_id) == 3600 - 30

    other, tenant = await _new_meeting(funded)
    async with db.session_scope(funded.tenant_id) as session:
        await billing.reserve(
            session, tenant=tenant, meeting_id=other.id, block=0, duration_ms=60_000
        )
    async with db.session_scope(funded.tenant_id) as session:
        # The recording ran longer than the hold: the difference comes out of the balance.
        await billing.settle(
            session, tenant_id=funded.tenant_id, meeting_id=other.id, actual_duration_ms=100_000
        )
        assert await _balance(session, funded.tenant_id) == 3600 - 30 - 100


@requires_postgres
async def test_release_returns_every_block_once(funded) -> None:
    meeting, tenant = await _new_meeting(funded)
    async with db.session_scope(funded.tenant_id) as session:
        for block in range(3):
            await billing.reserve(
                session, tenant=tenant, meeting_id=meeting.id, block=block, duration_ms=120_000
            )
        assert await _balance(session, funded.tenant_id) == 3600 - 360
    async with db.session_scope(funded.tenant_id) as session:
        await billing.release(session, tenant_id=funded.tenant_id, meeting_id=meeting.id)
        await billing.release(session, tenant_id=funded.tenant_id, meeting_id=meeting.id)
        assert await _balance(session, funded.tenant_id) == 3600
        released = (
            await session.execute(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.meeting_id == meeting.id, LedgerEntry.kind == "release")
            )
        ).scalar_one()
        assert released == 3


@requires_postgres
async def test_a_block_larger_than_the_balance_is_refused(funded) -> None:
    meeting, tenant = await _new_meeting(funded)
    async with db.session_scope(funded.tenant_id) as session:
        with pytest.raises(ApiError) as short:
            await billing.reserve(
                session, tenant=tenant, meeting_id=meeting.id, block=0, duration_ms=10_000_000
            )
    assert short.value.code == "insufficient_credit"
