"""Meeting attendees: migration 0116 (static), request schema and the minutes prompt header."""

from __future__ import annotations

import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import MeetingAttendeeIn, MeetingDetail, MeetingSessionIn
from app.services.meeting_minutes import _Context, _user_message

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"


def _load():
    spec = importlib.util.spec_from_file_location("m0116", VERSIONS / "0116_meeting_attendees.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(direction: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    getattr(module, direction)()
    return statements


def test_migration_continues_the_chain() -> None:
    module = _load()
    assert module.revision == "0116_meeting_attendees"
    assert module.down_revision == "0115_jalase_negar_install_help"


def test_table_is_granted_and_row_level_secured(monkeypatch) -> None:
    sql = _run("upgrade", monkeypatch)
    joined = "\n".join(sql)
    assert re.search(r"CREATE TABLE meeting_attendees", joined)
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON meeting_attendees TO cbi_app" in joined
    assert "ENABLE ROW LEVEL SECURITY" in joined and "FORCE ROW LEVEL SECURITY" in joined
    assert "meeting_attendees_tenant_isolation" in joined
    assert all(not s.rstrip().endswith(";") for s in sql)


def test_downgrade_drops_the_table(monkeypatch) -> None:
    assert _run("downgrade", monkeypatch) == ["DROP TABLE IF EXISTS meeting_attendees"]


def _body(**extra: object) -> dict[str, object]:
    return {
        "client_meeting_id": str(uuid4()),
        "started_at": datetime.now(UTC).isoformat(),
        "sample_rate": 16000,
        "channels": 1,
        "app_version": "1.0.0",
        **extra,
    }


def test_session_without_attendees_still_validates() -> None:
    assert MeetingSessionIn.model_validate(_body()).attendees == []


def test_attendee_names_are_trimmed_and_must_be_text() -> None:
    ok = MeetingAttendeeIn(profile_client_id=uuid4(), name="  علی رضایی ")
    assert ok.name == "علی رضایی"
    for bad in ("", "   ", "a\nb", "x" * 81):
        with pytest.raises(ValidationError):
            MeetingAttendeeIn(profile_client_id=uuid4(), name=bad)


def test_attendee_list_is_capped() -> None:
    many = [{"profile_client_id": str(uuid4()), "name": "n"} for _ in range(65)]
    with pytest.raises(ValidationError):
        MeetingSessionIn.model_validate(_body(attendees=many))


def test_detail_defaults_to_no_attendees() -> None:
    assert MeetingDetail.model_fields["attendees"].default_factory is not None


def _ctx(attendees: tuple[str, ...]) -> _Context:
    return _Context(
        title="t",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_ms=60_000,
        transcript="[00:01] x",
        base_prompt="",
        org_instructions="",
        block_chars=1000,
        runtime=None,
        provider="p",
        version=1,
        attendees=attendees,
    )


def test_minutes_prompt_lists_the_attendees_when_there_are_any() -> None:
    with_names = _user_message(_ctx(("سارا", "علی")), "متن", summaries=False)
    assert "حاضران ثبت‌شده" in with_names and "سارا، علی" in with_names
    assert "حاضران ثبت‌شده" not in _user_message(_ctx(()), "متن", summaries=False)


def test_help_article_migration_is_sound() -> None:
    from app.services.help_content import sanitize_help_html

    spec = importlib.util.spec_from_file_location(
        "m0117", VERSIONS / "0117_meeting_attendees_help.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0117_meeting_attendees_help"
    assert module.down_revision == "0116_meeting_attendees"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", module.SLUG)
    body_html, body_plain = module._body()
    assert "JN-REC-0005" in body_plain
    cleaned, _ = sanitize_help_html(body_html)
    assert cleaned.count("<li>") == body_html.count("<li>") == 5
