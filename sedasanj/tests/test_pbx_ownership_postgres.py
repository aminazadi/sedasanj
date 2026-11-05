"""Run against an isolated PostgreSQL database using PBX_TEST_DATABASE_URL."""

import asyncio
from datetime import UTC, datetime, timedelta
from os import environ
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.deps import Principal
from app.errors import ApiError
from app.models import (
    AudioObject,
    Base,
    Call,
    CallOperatorAssignment,
    Contact,
    PbxExtension,
    Tenant,
    User,
)
from app.routers.ingest import ingest_missed_call
from app.schemas import MissedCallIngest
from app.services import call_parties, call_party_review, extensions, operator_scope

DATABASE_URL = environ.get("PBX_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires an isolated PostgreSQL database")


async def test_pbx_owner_snapshot_and_review() -> None:
    assert DATABASE_URL
    engine = create_async_engine(DATABASE_URL)
    schema = f"pbx_test_{uuid4().hex}"
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await connection.execute(text(f"CREATE SCHEMA {schema}"))
            await connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))
            models = (
                Tenant,
                User,
                Contact,
                AudioObject,
                Call,
                PbxExtension,
                CallOperatorAssignment,
            )
            await connection.run_sync(
                lambda conn: Base.metadata.create_all(
                    conn, tables=[model.__table__ for model in models]
                )
            )
        scoped_engine = engine.execution_options(schema_translate_map={None: schema})
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)
        tenant_id, other_tenant_id, host, caller_id, callee_id = (uuid4() for _ in range(5))
        async with sessions.begin() as session:
            session.add_all(
                Tenant(id=tenant, name="PBX test", price_per_minute_toman=0)
                for tenant in (tenant_id, other_tenant_id)
            )
            await session.flush()
            session.add_all(
                User(
                    id=user_id,
                    tenant_id=tenant,
                    role="operator",
                    email=email,
                    extension=extension,
                    password_hash="unused",
                )
                for user_id, tenant, email, extension in (
                    (caller_id, tenant_id, "origin@example.test", "۰۱۰۱"),
                    (callee_id, tenant_id, "destination@example.test", "102"),
                    (uuid4(), other_tenant_id, "other@example.test", "102"),
                )
            )
        snapshot = [("0101", "Origin"), ("102", "Destination")]
        async with sessions.begin() as session:
            await extensions.sync(session, tenant_id, snapshot, host)
        for rejected_host in (None, uuid4()):
            async with sessions.begin() as session:
                with pytest.raises(ApiError) as exc:
                    await extensions.sync(session, tenant_id, [("999", None)], rejected_host)
                assert exc.value.code == "pbx_source_conflict"
        started = datetime.now(UTC)
        missed = MissedCallIngest(
            asterisk_uniqueid="pbx-test-missed",
            caller_number="09121234567",
            dialed_number="102",
            dialed_extension="102",
            pbx_evidence="direct",
            direction="inbound",
            started_at=started,
            ended_at=started + timedelta(seconds=3),
        )
        async with sessions.begin() as session:
            first = await ingest_missed_call(
                Principal("api_key", uuid4(), tenant_id, "ingest"), session, missed, host
            )
        async with sessions.begin() as session:
            replay = await ingest_missed_call(
                Principal("api_key", uuid4(), tenant_id, "ingest"), session, missed, host
            )
            assert replay["replayed"] is True
            assert replay["call_id"] == first["call_id"]
        async with sessions.begin() as session:
            parties = await call_parties.resolve(
                session,
                tenant_id,
                host_uuid=host,
                direction="internal",
                caller_extension="0101",
                dialed_extension="102",
                evidence="cdr",
            )
            assert await call_parties.assignments_for(session, tenant_id, parties, "answered") == {
                caller_id: ("0101", "caller"),
                callee_id: ("102", "callee"),
            }
            mismatch = await call_parties.resolve(
                session, tenant_id, host_uuid=uuid4(), direction="internal", evidence="cdr"
            )
            assert mismatch.evidence == "ambiguous"
            assert not mismatch.operator_candidates("answered")

            started = datetime.now(UTC) + timedelta(seconds=1)
            call = Call(
                tenant_id=tenant_id,
                asterisk_uniqueid="pbx-test-internal",
                caller_number="0101",
                dialed_number="102",
                direction="internal",
                caller_extension="0101",
                dialed_extension="102",
                agent_extension="102",
                pbx_evidence="cdr",
                call_type="answered",
                started_at=started,
                ended_at=started + timedelta(seconds=2),
                duration_ms=2000,
                status="received",
            )
            session.add(call)
            await session.flush()
            preview, _, _ = await call_party_review.preview(session, call)
            token = preview["token"]
            assert token
            assert await call_party_review.apply(session, call, token)
            assert await call_party_review.apply(session, call, token) is None
            call_id = call.id

        sync_started = asyncio.Event()

        async def resync() -> None:
            async with sessions.begin() as session:
                sync_started.set()
                await extensions.sync(session, tenant_id, snapshot, host)

        async with sessions.begin() as session:
            await extensions.lock_inventory(session, tenant_id)
            resync_task = asyncio.create_task(resync())
            await sync_started.wait()
            await extensions.reconcile_operator(session, tenant_id, callee_id, None)
            assert not resync_task.done()
        await resync_task
        async with sessions.begin() as session:
            assignments = (
                await session.scalars(
                    select(CallOperatorAssignment).where(
                        CallOperatorAssignment.call_id == call_id,
                        CallOperatorAssignment.superseded_at.is_(None),
                    )
                )
            ).all()
            for operator_id in (caller_id, callee_id):
                principal = Principal("user", operator_id, tenant_id, "operator")
                scoped = operator_scope.apply_operator_scope(
                    select(Call).where(Call.id == call_id), principal
                )
                assert (await session.scalar(scoped)) is not None
            assert {assignment.operator_id for assignment in assignments} == {caller_id, callee_id}
            assert await call_parties.assignments_for(session, tenant_id, parties, "answered") == {
                caller_id: ("0101", "caller")
            }
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await engine.dispose()
