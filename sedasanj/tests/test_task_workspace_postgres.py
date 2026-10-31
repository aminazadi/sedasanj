"""Exercise the workspace against an explicitly supplied disposable PostgreSQL database."""

import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.requests import Request

from app.deps import Principal
from app.errors import ApiError
from app.models import (
    AuditEvent,
    Call,
    CallOperatorAssignment,
    FollowUpTask,
    FollowUpTaskEvent,
    Tenant,
    User,
)
from app.routers import tasks
from app.schemas import TaskCreate, TaskNote, TaskUpdate
from app.services.follow_up_tasks import sync_from_analysis

DSN = os.environ.get("TASK_WORKSPACE_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="TASK_WORKSPACE_TEST_DSN must be disposable")


@pytest.fixture
async def workspace():
    engine = create_async_engine(DSN)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await connection.execute(text("CREATE TABLE audio_objects (id uuid PRIMARY KEY)"))
        for model in (
            Tenant,
            User,
            Call,
            CallOperatorAssignment,
            FollowUpTask,
            FollowUpTaskEvent,
            AuditEvent,
        ):
            await connection.run_sync(lambda sync, m=model: m.__table__.create(sync))
        async with AsyncSession(connection, expire_on_commit=False) as session:
            tenant = Tenant(
                id=uuid4(),
                name="Workspace",
                price_per_minute_toman=100,
                timezone="Pacific/Kiritimati",
            )
            other = Tenant(id=uuid4(), name="Other", price_per_minute_toman=100)
            session.add_all([tenant, other])
            await session.flush()
            manager = User(
                id=uuid4(),
                tenant_id=tenant.id,
                email="manager@example.test",
                password_hash="unused",
                role="org_admin",
                display_name="Manager",
            )
            operator = User(
                id=uuid4(),
                tenant_id=tenant.id,
                email="op@example.test",
                password_hash="unused",
                role="operator",
                display_name="Operator",
            )
            outsider = User(
                id=uuid4(),
                tenant_id=other.id,
                email="other@example.test",
                password_hash="unused",
                role="org_admin",
            )
            session.add_all([manager, operator, outsider])
            await session.flush()
            now = datetime.now(UTC)
            calls = [
                Call(
                    id=uuid4(),
                    tenant_id=t,
                    asterisk_uniqueid=str(uuid4()),
                    started_at=now,
                    ended_at=now,
                    duration_ms=1000,
                    status="complete",
                    direction=direction,
                    caller_number="09120000000",
                    dialed_number="100",
                )
                for t, direction in [
                    (tenant.id, "inbound"),
                    (tenant.id, "internal"),
                    (other.id, "inbound"),
                ]
            ]
            session.add_all(calls)
            await session.flush()
            assignment = CallOperatorAssignment(
                tenant_id=tenant.id,
                call_id=calls[0].id,
                operator_id=operator.id,
                agent_extension="100",
                assignment_source="test",
            )
            session.add(assignment)
            await session.flush()

            def principal(u):
                return Principal(kind="user", id=u.id, tenant_id=u.tenant_id, role=u.role)

            yield (
                session,
                principal(manager),
                principal(operator),
                principal(outsider),
                calls,
                assignment,
            )
        await transaction.rollback()
    await engine.dispose()


def request():
    return Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})


async def page(session, principal, **overrides):
    args = {
        "view": "all",
        "q": "",
        "status": None,
        "priority": None,
        "assignee_id": None,
        "unassigned": False,
        "due_from": None,
        "due_to": None,
        "sort": "due_date",
        "order": "asc",
        "limit": 25,
        "offset": 0,
    }
    args.update(overrides)
    return await tasks.list_tasks(principal=principal, session=session, **args)


async def create(session, principal, call_id, **values):
    return await tasks.create_task(
        TaskCreate(call_id=call_id, title="Follow up", **values), request(), principal, session
    )


async def test_sql_pagination_counts_timezone_and_search(workspace):
    session, manager, operator, outsider, calls, _ = workspace
    today, _ = await tasks.follow_up_tasks.tenant_today(session, manager.tenant_id)
    for index in range(9):
        await create(
            session,
            manager,
            calls[0].id,
            due_date=None if index == 0 else today + timedelta(days=index - 4),
        )
    await create(session, outsider, calls[2].id)
    first = await page(session, manager, limit=3)
    second = await page(session, manager, limit=3, offset=3)
    assert first.total == 9 and len(first.items) == 3
    assert {t.id for t in first.items}.isdisjoint(t.id for t in second.items)
    assert first.today == today
    assert first.counts == {"all": 9, "today": 5, "overdue": 3, "upcoming": 4, "done": 0}
    filtered = await page(session, manager, view="upcoming", q="۰۹۱۲")
    assert filtered.total == 4 and filtered.counts == first.counts
    assert (await page(session, operator)).total == 9
    assert (await page(session, outsider)).total == 1
    assert (await page(session, manager, offset=100)).items == []
    assert (await page(session, manager, q="%_")).total == 0
    with pytest.raises(ApiError, match="correct the date range"):
        await page(session, manager, due_from=today, due_to=today - timedelta(days=1))


async def test_assignment_visibility_history_and_version_conflicts(workspace):
    session, manager, operator, outsider, calls, assignment = workspace
    task = await create(session, manager, calls[0].id)
    assert task.origin == "manual" and task.version == 1 and task.assignee_id is None
    eligible = await tasks.task_assignees(calls[0].id, manager, session)
    assert {p.id for p in eligible} == {manager.id, operator.id}
    with pytest.raises(ApiError) as err:
        await tasks.update_task(
            task.id, TaskUpdate(version=1, assignee_id=outsider.id), request(), manager, session
        )
    assert err.value.code == "task_assignee_invalid"
    with pytest.raises(ApiError) as err:
        await tasks.update_task(
            task.id, TaskUpdate(version=1, assignee_id=operator.id), request(), operator, session
        )
    assert err.value.code == "forbidden"
    updated = await tasks.update_task(
        task.id,
        TaskUpdate(version=1, assignee_id=operator.id, status="in_progress"),
        request(),
        manager,
        session,
    )
    assert updated.version == 2 and updated.assignee_access_valid
    with pytest.raises(ApiError) as err:
        await tasks.update_task(
            task.id, TaskUpdate(version=1, status="done"), request(), operator, session
        )
    assert err.value.code == "task_version_conflict"
    noted = await tasks.add_note(
        task.id, TaskNote(version=2, note="Called customer"), request(), operator, session
    )
    assert noted.version == 3
    done = await tasks.update_task(
        task.id, TaskUpdate(version=3, status="done"), request(), operator, session
    )
    assert done.completed_at is not None
    reopened = await tasks.update_task(
        task.id, TaskUpdate(version=4, status="in_progress"), request(), operator, session
    )
    assert reopened.completed_at is None
    history = await tasks.task_history(task.id, manager, session, limit=2, offset=0)
    older = await tasks.task_history(task.id, manager, session, limit=2, offset=2)
    assert history.total == 5 and len(history.items) == 2
    assert {e.id for e in history.items}.isdisjoint(e.id for e in older.items)
    events = (
        await session.scalars(select(FollowUpTaskEvent).where(FollowUpTaskEvent.task_id == task.id))
    ).all()
    changes = next(e.changes for e in events if "assignee_id" in e.changes)
    assert changes["status"] == {"before": "open", "after": "in_progress"}
    assignment.superseded_at = datetime.now(UTC)
    await session.flush()
    assert not (await tasks.task_detail(task.id, manager, session)).assignee_access_valid
    with pytest.raises(ApiError) as err:
        await tasks.task_detail(task.id, operator, session)
    assert err.value.code == "not_found"
    with pytest.raises(ApiError) as err:
        await tasks.add_note(
            task.id, TaskNote(version=5, note="Hidden"), request(), outsider, session
        )
    assert err.value.code == "not_found"
    with pytest.raises(ApiError) as err:
        await tasks.update_task(
            task.id, TaskUpdate(version=5, assignee_id=operator.id), request(), manager, session
        )
    assert err.value.code == "task_assignee_invalid"


async def test_atomic_history_and_creation_scope(workspace):
    session, manager, operator, outsider, calls, _ = workspace
    for call_id, principal in [(calls[2].id, manager), (calls[0].id, outsider)]:
        with pytest.raises(ApiError) as err:
            await create(session, principal, call_id)
        assert err.value.code == "not_found"
    with pytest.raises(ApiError):
        await create(session, manager, calls[1].id)
    task = await create(session, operator, calls[0].id)
    async with session.begin_nested() as savepoint:
        await tasks.update_task(
            task.id, TaskUpdate(version=1, title="Changed"), request(), operator, session
        )
        await savepoint.rollback()
    fresh = await tasks.task_detail(task.id, operator, session)
    assert fresh.title == "Follow up" and fresh.version == 1
    assert await session.scalar(select(func.count()).select_from(FollowUpTaskEvent)) == 1
    created = await sync_from_analysis(session, calls[0], ["Automatic", "Automatic"])
    await session.flush()
    assert len(created) == 1 and created[0].origin == "analysis"
    assert await sync_from_analysis(session, calls[0], ["Automatic"]) == []
    assert await sync_from_analysis(session, calls[1], ["Internal"]) == []


async def test_migration_roundtrip_rls_and_help(workspace):
    session, manager, _, _, calls, _ = workspace
    connection = await session.connection()
    await connection.execute(text("DROP TABLE follow_up_task_events"))
    for name in ("idx_tasks_assignee", "idx_tasks_updated"):
        await connection.execute(text(f"DROP INDEX {name}"))
    for name in ("assignee_id", "origin", "version"):
        await connection.execute(text(f"ALTER TABLE follow_up_tasks DROP COLUMN {name}"))
    await connection.execute(
        text("ALTER TABLE follow_up_tasks DROP CONSTRAINT follow_up_tasks_status_check")
    )
    await connection.execute(
        text(
            "ALTER TABLE follow_up_tasks ADD CONSTRAINT follow_up_tasks_status_check "
            "CHECK(status IN ('open','done'))"
        )
    )
    await connection.execute(text("CREATE ROLE cbi_app NOLOGIN"))
    await connection.execute(
        text(
            "CREATE TABLE help_articles (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), slug "
            "varchar(120) UNIQUE, title varchar(250), summary text, body_html text, "
            "body_plain text, kind varchar(16), status varchar(16), position int, "
            "published_at timestamptz)"
        )
    )
    await connection.execute(
        text(
            "CREATE TABLE help_error_codes (code text PRIMARY KEY, article_id uuid "
            "REFERENCES help_articles(id), source text, severity text, title text, "
            "quick_action text)"
        )
    )
    path = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions/0091_task_workspace.py"
    spec = importlib.util.spec_from_file_location("workspace_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def migrate(sync, direction):
        with Operations.context(MigrationContext.configure(sync)):
            getattr(module, direction)()

    await connection.run_sync(lambda sync: migrate(sync, "upgrade"))
    await create(session, manager, calls[0].id)
    article = (
        await connection.execute(
            text("SELECT title,summary,body_html,body_plain FROM help_articles WHERE slug=:slug"),
            {"slug": module.ARTICLE_SLUG},
        )
    ).one()
    assert article == (
        module.ARTICLE_TITLE,
        module.ARTICLE_TITLE,
        module.ARTICLE_BODY,
        module.ARTICLE_TITLE,
    )
    assert await connection.scalar(text("SELECT count(*) FROM help_error_codes")) == 2
    flags = (
        await connection.execute(
            text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE "
                "relname='follow_up_task_events'"
            )
        )
    ).one()
    assert flags == (True, True)
    await connection.execute(text("SET LOCAL ROLE cbi_app"))
    await connection.execute(
        text("SELECT set_config('app.tenant_id',:id,true)"), {"id": str(manager.tenant_id)}
    )
    assert await connection.scalar(text("SELECT count(*) FROM follow_up_task_events")) == 1
    await connection.execute(
        text("SELECT set_config('app.tenant_id',:id,true)"), {"id": str(uuid4())}
    )
    assert await connection.scalar(text("SELECT count(*) FROM follow_up_task_events")) == 0
    await connection.execute(text("RESET ROLE"))
    await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert await connection.scalar(text("SELECT to_regclass('follow_up_task_events')")) is None
    await connection.run_sync(lambda sync: migrate(sync, "upgrade"))
    assert await connection.scalar(text("SELECT count(*) FROM follow_up_task_events")) == 0


async def test_concurrent_edits_allow_only_one_writer():
    import asyncio

    schema = "task_workspace_" + uuid4().hex
    setup = create_async_engine(DSN)
    engine = create_async_engine(
        DSN, connect_args={"server_settings": {"search_path": f"{schema},public"}}
    )
    try:
        async with setup.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE audio_objects (id uuid PRIMARY KEY)"))
            for model in (
                Tenant,
                User,
                Call,
                CallOperatorAssignment,
                FollowUpTask,
                FollowUpTaskEvent,
                AuditEvent,
            ):
                await conn.run_sync(lambda sync, m=model: m.__table__.create(sync))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tenant = Tenant(id=uuid4(), name="Concurrent", price_per_minute_toman=100)
            session.add(tenant)
            await session.flush()
            user = User(
                id=uuid4(),
                tenant_id=tenant.id,
                email="concurrent@example.test",
                password_hash="unused",
                role="org_admin",
            )
            now = datetime.now(UTC)
            call = Call(
                id=uuid4(),
                tenant_id=tenant.id,
                asterisk_uniqueid=str(uuid4()),
                started_at=now,
                ended_at=now,
                duration_ms=1000,
                status="complete",
                direction="inbound",
            )
            session.add_all([user, call])
            await session.flush()
            principal = Principal(kind="user", id=user.id, tenant_id=tenant.id, role=user.role)
            task = await create(session, principal, call.id)
            await session.commit()
        ready = asyncio.Event()

        async def edit(title):
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await ready.wait()
                try:
                    next_task = await tasks.update_task(
                        task.id, TaskUpdate(version=1, title=title), request(), principal, session
                    )
                    await session.commit()
                    return next_task.version
                except ApiError as exc:
                    await session.rollback()
                    return exc.code

        writers = [asyncio.create_task(edit(title)) for title in ("First writer", "Second writer")]
        ready.set()
        result = await asyncio.gather(*writers)
        assert sorted(map(str, result)) == ["2", "task_version_conflict"]
        async with AsyncSession(engine) as session:
            assert await session.scalar(select(func.count()).select_from(FollowUpTaskEvent)) == 2
    finally:
        await engine.dispose()
        async with setup.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await setup.dispose()


async def test_http_contract_validation_and_viewer_permissions(workspace):
    import httpx
    from fastapi import FastAPI

    from app.deps import current_user, tenant_session
    from app.errors import install_error_handlers

    session, manager, _, _, calls, _ = workspace
    app = FastAPI()
    app.include_router(tasks.router)
    install_error_handlers(app)
    principal = manager

    async def identity():
        return principal

    async def database():
        yield session

    app.dependency_overrides[current_user] = identity
    app.dependency_overrides[tenant_session] = database
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/tasks", json={"call_id": str(calls[0].id), "title": "Manual HTTP"}
        )
        assert response.status_code == 201
        task = response.json()
        response = await client.get("/v1/tasks", params={"view": "all", "limit": 10, "offset": 0})
        assert response.status_code == 200
        assert response.json()["total"] == 1 and response.json()["items"][0]["id"] == task["id"]
        assert (await client.get("/v1/tasks?limit=201")).status_code == 422
        assert (await client.get("/v1/tasks?offset=-1")).status_code == 422
        assert (await client.get("/v1/tasks?sort=unknown")).status_code == 422
        conflict = await client.patch(f"/v1/tasks/{task['id']}", json={"title": "Missing version"})
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "task_version_conflict"
        response = await client.patch(
            f"/v1/tasks/{task['id']}", json={"version": 1, "status": "in_progress"}
        )
        assert response.status_code == 200 and response.json()["version"] == 2
        response = await client.get("/v1/tasks?view=all&status=in_progress")
        assert response.json()["counts"]["today"] == 1
        principal = Principal(
            kind="user", id=manager.id, tenant_id=manager.tenant_id, role="viewer"
        )
        assert (await client.get(f"/v1/tasks/{task['id']}")).status_code == 200
        assert (
            await client.patch(f"/v1/tasks/{task['id']}", json={"version": 2, "title": "Denied"})
        ).status_code == 403
        assert (
            await client.post(
                f"/v1/tasks/{task['id']}/notes", json={"version": 2, "note": "Denied"}
            )
        ).status_code == 403


async def test_filters_sorting_and_counts_share_the_same_scope(workspace):
    session, manager, _, _, calls, _ = workspace
    today, _ = await tasks.follow_up_tasks.tenant_today(session, manager.tenant_id)
    high = await create(
        session, manager, calls[0].id, priority="high", due_date=today - timedelta(days=1)
    )
    low = await create(
        session, manager, calls[0].id, priority="low", due_date=today + timedelta(days=1)
    )
    normal = await create(session, manager, calls[0].id, priority="normal")
    await tasks.update_task(
        high.id, TaskUpdate(version=1, assignee_id=manager.id), request(), manager, session
    )
    await tasks.update_task(
        low.id, TaskUpdate(version=1, status="in_progress"), request(), manager, session
    )
    await tasks.update_task(
        normal.id, TaskUpdate(version=1, status="done"), request(), manager, session
    )
    result = await page(session, manager, sort="priority")
    assert [item.id for item in result.items] == [high.id, normal.id, low.id]
    result = await page(session, manager, assignee_id=manager.id, priority="high")
    assert result.total == 1 and result.counts["overdue"] == 1
    result = await page(session, manager, status="in_progress")
    assert result.total == 1 and result.counts["upcoming"] == 1
    result = await page(session, manager, due_from=today, due_to=today + timedelta(days=1))
    assert [item.id for item in result.items] == [low.id]
    assert (await page(session, manager, unassigned=True)).total == 2
    assert (await page(session, manager, q="۰۹۱۲۰۰۰۰۰۰۰")).total == 3
