from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import Call
from app.routers.kpi import DEFAULT_SETTINGS, KpiSettingsIn
from app.services import call_scope, follow_up_tasks, operator_coaching
from worker_llm.prompts import INTERNAL_CALL_NOTICE, with_call_context


def test_internal_speaker_labels_name_colleagues() -> None:
    labels = operator_coaching.speaker_labels("internal", "stereo")
    assert labels == {0: "همکار تماس‌گیرنده", 1: "همکار پاسخ‌دهنده"}
    assert operator_coaching.speaker_labels("inbound", "stereo")[0] == "مشتری"


def test_internal_call_counts_as_operator_speech() -> None:
    labels = operator_coaching.speaker_labels("internal", "stereo")
    utterances = [SimpleNamespace(channel=1, t_start_ms=0, text="سلام، فایل را فرستادم")]
    text, spoke = operator_coaching.format_transcript(utterances, labels)
    assert spoke
    assert "همکار پاسخ‌دهنده" in text


def test_internal_call_context_names_both_parties() -> None:
    context = operator_coaching.internal_call_context(("101", "علی"), ("102", None))
    assert "علی" in context
    assert "داخلی 102" in context
    assert "not a customer call" in context


def test_internal_prompt_is_about_colleagues_not_customers() -> None:
    assert "همکار" in operator_coaching.INTERNAL_CALL_PROMPT
    keys = {item["key"] for item in operator_coaching.INTERNAL_CALL_DIMENSIONS}
    assert len(keys) == len(operator_coaching.INTERNAL_CALL_DIMENSIONS)


def test_user_message_includes_internal_context() -> None:
    call = SimpleNamespace(
        direction="internal", duration_ms=60000, agent_extension="102", campaign_id=None
    )
    message = operator_coaching._user_message(
        call=call,  # type: ignore[arg-type]
        insight=None,
        operator_label="علی",
        transcript_text="x",
        tasks=[],
        internal_context="## Internal call context",
    )
    assert "## Internal call context" in message


def test_not_internal_clause_keeps_null_direction() -> None:
    sql = str(
        select(Call.id)
        .where(call_scope.not_internal_clause())
        .compile(dialect=postgresql.dialect())
    )
    assert "calls.direction IS NULL" in sql
    assert "calls.direction !=" in sql


def test_kpi_setting_defaults_to_excluding_internal_calls() -> None:
    assert DEFAULT_SETTINGS["include_internal_calls"] is False
    assert KpiSettingsIn.model_fields["include_internal_calls"].default is False


def test_extraction_notice_only_for_internal_calls() -> None:
    assert with_call_context("متن", "internal").startswith(INTERNAL_CALL_NOTICE)
    assert with_call_context("متن", "inbound") == "متن"
    assert with_call_context("متن", None) == "متن"


async def test_follow_up_tasks_skipped_for_internal_call() -> None:
    call = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), direction="internal")
    assert await follow_up_tasks.sync_from_analysis(None, call, ["پیگیری"]) == []  # type: ignore[arg-type]
