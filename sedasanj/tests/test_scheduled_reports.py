from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app import deps
from app.errors import ApiError, install_error_handlers
from app.models import ScheduledReport, ScheduledReportRun, Tenant
from app.routers import assistant
from app.routers import scheduled_reports as api
from app.services import assistant_agent, knowledge
from app.services import scheduled_reports as reports


class Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


@pytest.mark.parametrize(
    "after,expected",
    [
        (datetime(2026, 10, 17, 5, 29, tzinfo=UTC), datetime(2026, 10, 17, 5, 30, tzinfo=UTC)),
        (datetime(2026, 10, 17, 5, 30, tzinfo=UTC), datetime(2026, 10, 17, 14, 30, tzinfo=UTC)),
        (datetime(2026, 10, 17, 18, tzinfo=UTC), datetime(2026, 10, 18, 5, 30, tzinfo=UTC)),
    ],
)
def test_fixed_hours_respect_organization_timezone_and_are_strictly_future(after, expected):
    report = SimpleNamespace(schedule_mode="fixed", fixed_hours=[9, 18])
    assert reports.next_run_at(report, after, "Asia/Tehran") == expected


def test_interval_and_dst_missing_hour():
    now = datetime(2026, 10, 17, 10, tzinfo=UTC)
    report = SimpleNamespace(schedule_mode="interval", interval_hours=6)
    assert reports.next_run_at(report, now, "Asia/Tehran") == now + timedelta(hours=6)
    report = SimpleNamespace(schedule_mode="fixed", fixed_hours=[2])
    # 02:00 does not exist in New York on March 8, 2026.
    assert reports.next_run_at(
        report, datetime(2026, 3, 8, 6, tzinfo=UTC), "America/New_York"
    ) == datetime(2026, 3, 9, 6, tzinfo=UTC)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"instructions": " "},
        {"interval_hours": 0},
        {"schedule_mode": "fixed", "interval_hours": None, "fixed_hours": []},
        {"schedule_mode": "fixed", "interval_hours": None, "fixed_hours": [24]},
        {"schedule_mode": "fixed", "interval_hours": None, "fixed_hours": [9, 9]},
        {"fixed_hours": [9]},
    ],
)
def test_invalid_report_configuration(changes):
    with pytest.raises(ValidationError):
        api.ReportInput.model_validate({"name": "Report", "instructions": "Criteria", **changes})


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "", None),
        ("POST", "", {"name": "Report", "instructions": "Criteria"}),
        ("PUT", f"/{uuid4()}", {"name": "Report", "instructions": "Criteria"}),
        ("DELETE", f"/{uuid4()}", None),
        ("POST", f"/{uuid4()}/run", {"idempotency_key": str(uuid4())}),
        ("GET", "/runs", None),
        ("GET", f"/runs/{uuid4()}", None),
    ],
)
@pytest.mark.parametrize("role", ["operator", "viewer"])
async def test_every_endpoint_rejects_non_managers(method, path, body, role):
    app = FastAPI()
    app.include_router(api.router)
    install_error_handlers(app)
    app.dependency_overrides[deps.current_user] = lambda: deps.Principal(
        "user", uuid4(), uuid4(), role
    )

    async def forbidden_session():
        raise AssertionError("non-manager must not enter tenant session")

    app.dependency_overrides[deps.tenant_session] = forbidden_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, "/v1/scheduled-reports" + path, json=body)
    assert response.status_code == 403


async def test_other_organization_report_is_not_found():
    tenant, report = uuid4(), uuid4()

    class Session:
        async def execute(self, query):
            params = query.compile().params
            assert tenant in params.values() and report in params.values()
            return Result(None)

    with pytest.raises(ApiError) as error:
        await api.get_report(Session(), tenant, report, lock=True)
    assert error.value.code == "not_found"


async def test_manual_execution_preserves_schedule_and_snapshots_every_active_memory(monkeypatch):
    now = datetime.now(UTC)
    row = ScheduledReport(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Report",
        instructions="Criteria",
        window_start=now - timedelta(hours=6),
        next_run_at=now + timedelta(hours=6),
    )
    memories = [
        SimpleNamespace(
            id=uuid4(),
            version=i,
            title="Rule",
            category="policies",
            content=f"Rule {i}",
            structured_payload={},
            applies_to=[scope],
        )
        for i, scope in enumerate(["analysis", "scoring", "assistant", "correction"])
    ]
    staged = AsyncMock()
    monkeypatch.setattr(reports.outbox, "stage", staged)

    class Session:
        async def execute(self, query):
            params = query.compile().params
            assert row.tenant_id in params.values()
            assert "active" in params.values()
            return Result(memories)

        def add(self, run):
            self.run = run
            run.id = uuid4()

        async def flush(self):
            pass

    session = Session()
    next_at = row.next_run_at
    run = await reports.create_run(session, row, now, "Asia/Tehran", "manual", str(uuid4()))
    assert run.from_date == row.window_start
    assert run.to_date == now
    assert row.next_run_at == next_at
    assert {m["applies_to"][0] for m in run.memory_snapshot} == {
        "analysis",
        "scoring",
        "assistant",
        "correction",
    }
    assert staged.await_args.kwargs["payload"]["tenant_id"] == str(row.tenant_id)
    assert staged.await_args.kwargs["payload"]["run_id"] == str(run.id)


@pytest.mark.parametrize("retrieve", ["vector_call_context", "vector_transcript_context"])
async def test_vector_time_bounds_are_applied_before_ranking(monkeypatch, retrieve):
    start, end, tenant = (
        datetime(2026, 10, 17, tzinfo=UTC),
        datetime(2026, 10, 18, tzinfo=UTC),
        uuid4(),
    )
    monkeypatch.setattr(knowledge, "embed", AsyncMock(return_value=([0.1, 0.2], "model")))

    class Session:
        async def execute(self, query, params):
            sql = str(query)
            assert "c.started_at >= :from_date" in sql
            assert "c.started_at < :to_date" in sql
            assert sql.index("c.started_at <") < sql.index("ORDER BY")
            assert params["tenant_id"] == tenant
            assert params["from_date"] == start and params["to_date"] == end
            return []

    assert (
        await getattr(knowledge, retrieve)(
            Session(), tenant, "criteria", 20, None, from_date=start, to_date=end
        )
        == []
    )


@pytest.mark.parametrize("fail", [False, True])
async def test_worker_persists_success_failure_and_does_not_regenerate_completed_run(
    monkeypatch, fail
):
    tenant, admin, call = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    run = ScheduledReportRun(
        id=uuid4(),
        tenant_id=tenant,
        report_id=uuid4(),
        name="Report",
        instructions="Criteria",
        status="queued",
        from_date=now - timedelta(hours=6),
        to_date=now,
        timezone="Asia/Tehran",
        memory_snapshot=[
            {
                "title": "Analysis-only memory",
                "content": "Important rule",
                "applies_to": ["analysis"],
            }
        ],
        sources=[],
        coverage={},
    )
    usage = SimpleNamespace(id=uuid4(), status="reserved", model=None)

    class Session:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if sql.startswith("UPDATE"):
                return Result()
            if "FROM scheduled_report_runs" in sql:
                assert tenant in statement.compile().params.values()
                return Result(run)
            if "FROM users" in sql:
                return Result(SimpleNamespace(id=admin))
            if "FROM calls" in sql:
                return Result(3)
            if "FROM call_knowledge" in sql:
                return Result(1)
            raise AssertionError(sql)

        async def get(self, model, key):
            return SimpleNamespace(status="active") if model is Tenant else usage

    @asynccontextmanager
    async def scope(tenant_id=None, **kwargs):
        assert tenant_id == tenant or (tenant_id is None and kwargs.get("staff"))
        yield Session()

    monkeypatch.setattr(reports, "session_scope", scope)
    monkeypatch.setattr(
        assistant,
        "_reserve_assistant_usage",
        AsyncMock(return_value=(SimpleNamespace(assistant_model="model"), usage)),
    )
    monkeypatch.setattr(
        reports,
        "effective_models",
        AsyncMock(
            return_value={"assistant_provider": "aiservice", "assistant_max_tool_calls": "4"}
        ),
    )
    monkeypatch.setattr(reports, "resolve_provider_settings", AsyncMock())
    monkeypatch.setattr(
        reports.knowledge,
        "vector_call_context",
        AsyncMock(return_value=[{"call_id": call, "summary": "Evidence"}]),
    )
    monkeypatch.setattr(reports.knowledge, "vector_transcript_context", AsyncMock(return_value=[]))
    tool = AsyncMock(return_value={"count": 3, "items": []})
    monkeypatch.setattr(reports, "_tool", tool)
    monkeypatch.setattr(
        reports.assistant_agent, "plan", AsyncMock(return_value=assistant_agent.AgentPlan(None, []))
    )
    client = SimpleNamespace(
        complete=AsyncMock(
            side_effect=RuntimeError("provider failed") if fail else None,
            return_value=f'گزارش <call-sources>["{call}"]</call-sources>',
        ),
        close=AsyncMock(),
    )
    monkeypatch.setattr(reports, "build_client", lambda *args, **kwargs: client)
    payload = {"tenant_id": str(tenant), "run_id": str(run.id)}
    assert await reports.generate_scheduled_report({}, payload) == (
        "failed" if fail else "succeeded"
    )
    assert run.status == ("failed" if fail else "succeeded")
    assert usage.status == ("failed" if fail else "succeeded")
    if fail:
        assert run.error_detail and run.content is None
    else:
        assert "ایندکس وکتوری" in run.content
        assert run.sources == [{"call_id": str(call)}]
        assert "Important rule" in client.complete.await_args.args[1]
        assert run.coverage["calls"] == 3
        assert (
            tool.await_args_list[0].args[2]["to_date"]
            == (now - timedelta(microseconds=1)).isoformat()
        )
    assert await reports.generate_scheduled_report({}, payload) == "skipped"
    assert client.complete.await_count == 1


async def test_scheduler_advances_one_window_and_skips_active_execution(monkeypatch):
    tenant = uuid4()
    before = datetime.now(UTC) - timedelta(hours=12)
    row = ScheduledReport(
        id=uuid4(),
        tenant_id=tenant,
        name="Report",
        instructions="Criteria",
        enabled=True,
        schedule_mode="interval",
        interval_hours=6,
        fixed_hours=[],
        window_start=before,
        next_run_at=before + timedelta(hours=6),
    )
    active = False

    class Session:
        async def get(self, model, key):
            return SimpleNamespace(status="active", timezone="Asia/Tehran")

        async def execute(self, query):
            sql = str(query.compile(dialect=postgresql.dialect()))
            if sql.startswith("UPDATE"):
                return Result()
            if "FROM scheduled_reports" in sql:
                assert "SKIP LOCKED" in sql
                assert tenant in query.compile().params.values()
                return Result([row])
            return Result(uuid4() if active else None)

    @asynccontextmanager
    async def scope(*args, **kwargs):
        yield Session()

    monkeypatch.setattr(reports, "operational_tenant_ids", AsyncMock(return_value=[tenant]))
    monkeypatch.setattr(reports, "session_scope", scope)
    create = AsyncMock()
    monkeypatch.setattr(reports, "create_run", create)
    assert await reports.schedule_due_reports() == 1
    assert create.await_args.args[2] == row.window_start
    assert create.await_args.args[1] == row
    assert row.window_start > before
    assert row.next_run_at > row.window_start
    assert (row.next_run_at - before) % timedelta(hours=6) == timedelta(0)
    cursor = row.window_start
    active = True
    assert await reports.schedule_due_reports() == 0
    assert create.await_count == 1
    assert row.window_start == cursor


async def test_manual_idempotency_returns_existing_run_without_new_job(monkeypatch):
    tenant, user, report_id, key = uuid4(), uuid4(), uuid4(), uuid4()
    existing = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(api, "get_report", AsyncMock(return_value=SimpleNamespace(id=report_id)))
    create = AsyncMock()
    monkeypatch.setattr(api, "create_run", create)
    session = SimpleNamespace(execute=AsyncMock(return_value=Result(existing)))
    principal = deps.Principal("user", user, tenant, "org_admin")
    assert (
        await api.run_now(report_id, api.RunRequest(idempotency_key=key), None, principal, session)
        is existing
    )
    create.assert_not_awaited()


async def test_pause_resume_and_criteria_edits_preserve_existing_execution_snapshot(monkeypatch):
    tenant, user = uuid4(), uuid4()
    now = datetime.now(UTC)
    row = ScheduledReport(
        id=uuid4(),
        tenant_id=tenant,
        name="Report",
        instructions="Old criteria",
        enabled=True,
        schedule_mode="interval",
        interval_hours=6,
        fixed_hours=[],
        window_start=now - timedelta(hours=6),
        next_run_at=now + timedelta(hours=6),
    )
    run = ScheduledReportRun(instructions=row.instructions)
    monkeypatch.setattr(api, "get_report", AsyncMock(return_value=row))
    monkeypatch.setattr(api.audit, "record", AsyncMock())
    monkeypatch.setattr(api, "client_ip", lambda request: None)
    principal = deps.Principal("user", user, tenant, "org_admin")
    session = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(timezone="Asia/Tehran")))
    payload = api.ReportInput(
        name="Report", instructions="New criteria", interval_hours=6, enabled=False
    )
    await api.edit_report(row.id, payload, None, principal, session)
    assert row.next_run_at is None and not row.enabled
    assert run.instructions == "Old criteria"
    payload.enabled = True
    await api.edit_report(row.id, payload, None, principal, session)
    assert row.enabled and row.next_run_at > now
    assert row.window_start >= now
