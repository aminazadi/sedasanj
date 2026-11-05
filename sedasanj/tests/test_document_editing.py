"""Document edits preserve access boundaries and reject stale editor contents."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request
from pydantic import ValidationError

from app.errors import ERROR_STATUS, ApiError
from app.routers import meetings, scheduled_reports
from app.schemas import DocumentEdit


def payload(content="## Updated\n\nNew text", expected="Original"):
    return DocumentEdit(content=content, expected_content=expected)


def test_document_edit_validation():
    for content in ("", "   ", "x" * 500001):
        with pytest.raises(ValidationError):
            payload(content)
    assert payload().expected_content == "Original"
    assert ERROR_STATUS["document_edit_conflict"] == 409


@pytest.mark.parametrize("kind", ["minutes", "report"])
@pytest.mark.parametrize("state", ["success", "conflict", "processing", "missing"])
async def test_document_editing(monkeypatch, kind, state):
    principal = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)})
    audit = AsyncMock()
    session = SimpleNamespace(execute=AsyncMock())
    row = SimpleNamespace(
        id=uuid4(),
        status="processing" if state == "processing" else "succeeded",
        content="Changed" if state == "conflict" else "Original",
    )
    if kind == "report":
        monkeypatch.setattr(scheduled_reports.audit, "record", audit)
        session.execute.return_value = SimpleNamespace(
            scalar_one_or_none=lambda: None if state == "missing" else row
        )
        call = scheduled_reports.edit_run(row.id, payload(), request, principal, session)
    else:
        row.status = "processing" if state == "processing" else "complete"
        minutes = SimpleNamespace(
            version=2,
            content_md="Changed" if state == "conflict" else "Original",
            structured={"summary": "Original"},
            is_selected=True,
            model="test",
            provider="test",
            created_at=datetime.now(UTC),
        )
        monkeypatch.setattr(meetings, "_visible_meeting", AsyncMock(return_value=row))
        monkeypatch.setattr(
            meetings,
            "_selected_minutes",
            AsyncMock(return_value=None if state == "missing" else minutes),
        )
        monkeypatch.setattr(meetings.audit, "record", audit)
        call = meetings.edit_minutes(row.id, 2, payload(), request, session, principal)
    if state != "success":
        with pytest.raises(ApiError) as caught:
            await call
        expected = "document_edit_conflict" if state == "conflict" else "document_not_ready"
        if kind == "report" and state == "missing":
            expected = "not_found"
        assert caught.value.code == expected
        audit.assert_not_awaited()
    else:
        result = await call
        if kind == "minutes":
            assert result.content_md == payload().content
            assert result.summary == payload().content
            assert result.decisions == []
        else:
            assert result.content == payload().content
        audit.assert_awaited_once()
        assert "content" not in audit.call_args.kwargs["payload"]
        if kind == "report":
            query = session.execute.call_args.args[0]
            assert query._for_update_arg is not None
            assert "tenant_id" in str(query)


async def test_minutes_changed_selected_version_rejects_save(monkeypatch):
    row = SimpleNamespace(id=uuid4(), status="complete")
    monkeypatch.setattr(meetings, "_visible_meeting", AsyncMock(return_value=row))
    monkeypatch.setattr(
        meetings,
        "_selected_minutes",
        AsyncMock(return_value=SimpleNamespace(version=3, content_md="Original")),
    )
    with pytest.raises(ApiError) as caught:
        await meetings.edit_minutes(
            row.id, 2, payload(), SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
        )
    assert caught.value.code == "document_edit_conflict"


@pytest.mark.parametrize("kind,role", [("minutes", "viewer"), ("report", "operator")])
async def test_edit_routes_reject_insufficient_roles(kind, role):
    import httpx
    from fastapi import FastAPI

    from app import deps
    from app.errors import install_error_handlers

    app = FastAPI()
    app.include_router(meetings.router if kind == "minutes" else scheduled_reports.router)
    install_error_handlers(app)
    app.dependency_overrides[deps.current_user] = lambda: deps.Principal(
        "user", uuid4(), uuid4(), role
    )
    app.dependency_overrides[deps.tenant_session] = lambda: SimpleNamespace()
    path = (
        f"/v1/meetings/{uuid4()}/minutes/1"
        if kind == "minutes"
        else f"/v1/scheduled-reports/runs/{uuid4()}"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(path, json=payload().model_dump())
    assert response.status_code == 403


def test_document_edit_help_covers_error_and_sharing():
    import importlib

    guide = importlib.import_module("apps.api.alembic.versions.0105_document_editing_help")
    assert guide.ERROR in ERROR_STATUS
    assert "اشتراک" in " ".join(guide.STEPS)
    assert len(guide.RECOVERY) == 5
