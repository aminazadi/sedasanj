from __future__ import annotations

from pathlib import Path

from app.services.processing_events import sanitize_detail


def test_call_details_returns_processing_events_in_chronological_order() -> None:
    """The API orders the events oldest-to-newest, which is the timeline contract."""
    project_root = Path(__file__).parents[1]
    calls_source = (project_root / "apps/api/app/routers/calls.py").read_text(encoding="utf-8")
    timeline_source = (project_root / "web/client/src/pages/CallDetail.tsx").read_text(
        encoding="utf-8"
    )

    assert ".order_by(ProcessingEvent.created_at.desc(), ProcessingEvent.id.desc())" in calls_source
    assert "event_rows.reverse()" in calls_source
    assert "{events.map((event) => {" in timeline_source
    assert "{[...events].reverse().map((event) => {" not in timeline_source


def test_processing_event_kinds_cover_every_pipeline_job() -> None:
    project_root = Path(__file__).parents[1]
    model_source = (project_root / "apps/api/app/models.py").read_text(encoding="utf-8")
    migration_source = (
        project_root
        / "apps/api/alembic/versions/0034_repair_processing_event_kinds.py"
    ).read_text(encoding="utf-8")
    client_types = (project_root / "web/client/src/types.ts").read_text(encoding="utf-8")

    expected = ("pipeline", "asr", "emotion", "correction", "llm", "notify")
    for kind in expected:
        assert f"'{kind}'" in model_source
        assert f"'{kind}'" in migration_source
        assert f'"{kind}"' in client_types


def test_sanitize_detail_redacts_common_secret_formats() -> None:
    detail = (
        "Authorization: Bearer bearer-value "
        "api_key=plain-value "
        "https://user:password@example.test/path "
        "https://example.test/callback?access_token=query-value&ok=1"
    )

    sanitized = sanitize_detail(detail)

    assert sanitized is not None
    assert "bearer-value" not in sanitized
    assert "plain-value" not in sanitized
    assert "password" not in sanitized
    assert "query-value" not in sanitized
    assert sanitized.count("[REDACTED]") == 4


def test_sanitize_detail_removes_nuls_and_applies_public_limit() -> None:
    sanitized = sanitize_detail("failure\x00detail" + "x" * 50, limit=20)

    assert sanitized == "failure detailxxxxxx"
    assert len(sanitized) == 20
