from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app import deps
from app.errors import ERROR_STATUS, install_error_handlers
from app.models import Meeting, MeetingMinutes, ScheduledReportRun
from app.routers import meetings, scheduled_reports
from app.services import document_pdf
from app.services.assistant_agent import PlannedToolCall
from app.services.assistant_tools import ChartType, chart_payload
from app.services.scheduled_reports import report_charts, split_report_title


def test_report_title_is_separate_and_legacy_model_output_is_retained() -> None:
    assert split_report_title("# روند فروش ##\r\n\r\nمتن گزارش", "فروش") == (
        "روند فروش",
        "متن گزارش",
    )
    for answer in ("متن قدیمی", "# عنوان تنها", "# [متن](https://example.com)\nمتن"):
        assert split_report_title(answer, "فروش") == ("فروش", answer)


@pytest.mark.parametrize(
    "kind",
    [
        "bar",
        "horizontal_bar",
        "line",
        "area",
        "pie",
        "donut",
        "radar",
        "radial_bar",
        "scatter",
        "composed",
        "treemap",
        "funnel",
    ],
)
def test_report_keeps_tool_backed_data_and_chart_type(kind: ChartType) -> None:
    data = [{"label": "تیم فروش", "value": 16.5, "secondary_value": 21}]
    chart = chart_payload("operators", "عملکرد", kind, data, "امتیاز", "تماس", 1)
    selected = PlannedToolCall("visual", "visualize_statistics", {})
    unrelated = PlannedToolCall("other", "search_knowledge", {})
    assert report_charts(
        [(unrelated, {"charts": [chart]}), (selected, {"charts": [chart]})],
        {"call_types": {"answered": 200}},
    ) == [{**chart, "id": "visual-operators"}]
    assert report_charts([], {"call_types": {}}) == []


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.parametrize("status", ["ready", "pending", "missing", "render_error"])
@pytest.mark.parametrize("kind", ["report", "meeting"])
async def test_pdf_download_uses_existing_scope_and_returns_private_response(
    monkeypatch, kind, status
) -> None:
    tenant_id, user_id, document_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    principal = deps.Principal(
        "user", user_id, tenant_id, "org_admin" if kind == "report" else "operator"
    )
    report = ScheduledReportRun(
        id=document_id,
        tenant_id=tenant_id,
        title=None,
        name="گزارش پشتیبانی",
        status="queued" if status == "pending" else "succeeded",
        from_date=now - timedelta(days=1),
        to_date=now,
        timezone="Asia/Tehran",
        content="## یافته‌ها\n\n۱۲ تماس ثبت شده است.",
        charts=[],
    )
    meeting = Meeting(
        id=document_id,
        tenant_id=tenant_id,
        owner_user_id=user_id,
        title="هماهنگی تیم",
        duration_ms=64000,
        started_at=now,
    )
    minutes = MeetingMinutes(
        meeting_id=document_id,
        version=2,
        content_md="",
        created_at=now,
        is_selected=True,
        structured={
            "summary": "خلاصه نسخه فعال",
            "decisions": ["بررسی گزارش"],
            "action_items": [{"text": "پیگیری تماس", "assignee": "تیم محصول", "due": "فردا"}],
        },
    )

    class Session:
        async def execute(self, statement):
            params = statement.compile().params.values()
            assert document_id in params
            if "FROM meeting_minutes" in str(statement):
                assert "is_selected DESC" in str(statement)
                return Result(None if status == "pending" else minutes)
            assert tenant_id in params
            if kind == "meeting":
                assert user_id in params
            return Result(None if status == "missing" else report if kind == "report" else meeting)

        async def get(self, model, key):
            assert key == user_id
            return SimpleNamespace(display_name="تیم محصول")

    if status == "render_error":

        def broken(_document):
            raise RuntimeError("fixture failure")

        monkeypatch.setattr(document_pdf, "render", broken)

    app = FastAPI()
    app.include_router(scheduled_reports.router if kind == "report" else meetings.router)
    install_error_handlers(app)
    app.dependency_overrides[deps.current_user] = lambda: principal
    app.dependency_overrides[deps.tenant_session] = Session
    path = (
        f"/v1/scheduled-reports/runs/{document_id}/pdf"
        if kind == "report"
        else f"/v1/meetings/{document_id}/minutes/pdf"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(path)
    if status == "ready":
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["cache-control"] == "private, no-store"
        assert "filename*=UTF-8''" in response.headers["content-disposition"]
        assert response.content.startswith(b"%PDF-")
        assert b"/FontFile2" in response.content
    else:
        code = {
            "pending": "document_not_ready",
            "missing": "not_found" if kind == "report" else "meeting_not_found",
            "render_error": "document_pdf_unavailable",
        }[status]
        assert response.status_code == ERROR_STATUS[code]
        assert response.json()["error"]["code"] == code


def test_document_errors_have_actionable_help() -> None:
    migration = importlib.import_module("apps.api.alembic.versions.0101_report_documents")
    for code in ("document_not_ready", "document_pdf_unavailable"):
        [article] = [article for article in migration.ARTICLES if article[2] == code]
        assert article[3] and len(article[4]) >= 4
