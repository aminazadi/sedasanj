from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.errors import ApiError
from app.models import PlatformSetting
from app.routers import admin
from app.schemas import CoachIssue, CoachResult, SettingsUpdate
from app.services import operator_coaching as coaching
from app.services import platform
from worker_llm.client import available_prompt_versions, load_prompt


def _utterance(channel: int, start_ms: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(channel=channel, t_start_ms=start_ms, t_end_ms=start_ms + 500, text=text)


def test_speaker_labels_follow_call_direction_and_mono() -> None:
    assert coaching.speaker_labels("inbound", None) == {0: "مشتری", 1: "اپراتور"}
    assert coaching.speaker_labels("outbound", None) == {0: "اپراتور", 1: "مشتری"}
    assert coaching.speaker_labels("inbound", "mono_diarized")[0] == "گوینده ۱"
    assert coaching.speaker_labels(None, None)[0] == "کانال ۱"


def test_format_transcript_merges_consecutive_turns_and_flags_operator() -> None:
    labels = coaching.speaker_labels("inbound", None)
    text, operator_spoke = coaching.format_transcript(
        [
            _utterance(1, 4000, "بفرمایید"),
            _utterance(0, 0, "سلام"),
            _utterance(0, 1000, "سفارشم نرسیده"),
        ],
        labels,
    )
    lines = text.splitlines()
    assert lines[0] == "[نوبت 1 | 00:00] مشتری: سلام سفارشم نرسیده"
    assert lines[1] == "[نوبت 2 | 00:04] اپراتور: بفرمایید"
    assert operator_spoke is True


def test_customer_only_transcript_has_no_operator_speech() -> None:
    labels = coaching.speaker_labels("inbound", None)
    _, operator_spoke = coaching.format_transcript([_utterance(0, 0, "الو؟")], labels)
    assert operator_spoke is False


def test_quote_grounding_accepts_verbatim_and_rejects_invented_text() -> None:
    transcript = "[نوبت 2] اپراتور: ببخشید شماره سفارش‌تان چند بود؟"
    assert coaching.quote_is_grounded("ببخشید شماره سفارش‌تان چند بود", transcript)
    assert not coaching.quote_is_grounded("این جمله هرگز گفته نشده است اصلا", transcript)


def _issue(quote: str, severity: str = "medium") -> CoachIssue:
    return CoachIssue(severity=severity, title="مشکل", evidence_quote=quote)  # type: ignore[arg-type]


def test_verify_quotes_drops_ungrounded_issues_and_ranks_by_severity() -> None:
    result = CoachResult(
        headline="سرنخ اصلی",
        narrative="متن",
        issues=[
            _issue("جمله ساختگی که وجود ندارد در متن"),
            _issue("شماره سفارش‌تان چند بود", "low"),
            _issue("بفرمایید", "high"),
        ],
    )
    verified = coaching.verify_quotes(result, "اپراتور: بفرمایید. شماره سفارش‌تان چند بود؟")
    assert [issue.severity for issue in verified.issues] == ["high", "low"]
    assert all(issue.evidence_verified for issue in verified.issues)


def test_coach_result_requires_headline_and_narrative_unless_insufficient() -> None:
    with pytest.raises(ValidationError):
        CoachResult(headline="", narrative="")
    assert CoachResult(insufficient_evidence=True, insufficient_reason="کوتاه").issues == []


def test_coach_result_rejects_issue_without_evidence() -> None:
    with pytest.raises(ValidationError):
        CoachResult(
            headline="h",
            narrative="n",
            issues=[{"title": "بدون شاهد", "evidence_quote": ""}],  # type: ignore[list-item]
        )


def test_format_history_is_bounded_and_mentions_patterns() -> None:
    from datetime import UTC, datetime

    rows = [
        {
            "created_at": datetime(2026, 10, 1, tzinfo=UTC),
            "result": {
                "headline": "پرسش تکراری",
                "issues": [{"severity": "high", "dimension": "listening", "title": "تکرار سؤال"}],
                "next_call_drills": ["نام مشتری را بپرس"],
            },
        }
    ]
    text = coaching.format_history(rows, [("listening", 3)], 7)
    assert "7 earlier coached calls" in text
    assert "listening ×3" in text
    assert coaching.format_history([], [], 0) == ""


def test_packaged_prompt_is_not_an_analysis_prompt_and_demands_evidence() -> None:
    assert platform.COACH_PROMPT_VERSION not in available_prompt_versions()
    prompt = load_prompt(platform.COACH_PROMPT_VERSION)
    assert "evidence_quote" in prompt
    assert "better_phrase" in prompt
    assert "recurring" in prompt


def test_output_contract_names_every_dimension_key() -> None:
    from app.schemas import COACH_DIMENSION_KEYS

    for key in COACH_DIMENSION_KEYS:
        assert key in coaching.OUTPUT_CONTRACT


def test_capability_model_resolves_coach_for_both_providers() -> None:
    values = {
        "coach_provider": "aiservice",
        "coach_model": "m-a",
        "ninerouter_coach_model": "m-b",
    }
    assert platform.capability_model(values, "coach") == "m-a"
    direct = {**values, "coach_provider": "ninerouter_direct"}
    assert platform.capability_model(direct, "coach") == "m-b"


@pytest.mark.asyncio
async def test_effective_coach_prompt_prefers_admin_value_then_packaged_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        def __init__(self, row: PlatformSetting | None) -> None:
            self.row = row

        async def get(self, model: object, key: str) -> PlatformSetting | None:
            assert key == platform.COACH_PROMPT_KEY
            return self.row

    monkeypatch.setattr(
        platform, "get_settings", lambda: SimpleNamespace(tenant_databases_enabled=False)
    )
    custom = await platform.effective_coach_prompt(
        FakeSession(PlatformSetting(key=platform.COACH_PROMPT_KEY, value="  پرامپت من  "))  # type: ignore[arg-type]
    )
    assert custom == "پرامپت من"
    blank = await platform.effective_coach_prompt(
        FakeSession(PlatformSetting(key=platform.COACH_PROMPT_KEY, value="  "))  # type: ignore[arg-type]
    )
    assert blank == load_prompt(platform.COACH_PROMPT_VERSION)
    missing = await platform.effective_coach_prompt(FakeSession(None))  # type: ignore[arg-type]
    assert missing == blank


@pytest.mark.asyncio
async def test_settings_update_persists_coach_prompt_under_its_own_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, PlatformSetting] = {}
    audited: dict[str, object] = {}

    class FakeSession:
        async def get(self, model: object, key: str) -> PlatformSetting | None:
            return saved.get(key)

        def add(self, row: PlatformSetting) -> None:
            saved[row.key] = row

        async def flush(self) -> None:
            pass

    async def fake_audit(*args: object, **kwargs: object) -> None:
        audited.update(kwargs.get("payload") or {})  # type: ignore[call-overload]

    async def fake_view(session: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "settings_public_view", fake_view)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")

    await admin.update_platform_settings(
        SettingsUpdate(coach_prompt="  مربی سخت‌گیر  ", coach_model="", coach_enabled=False),
        None,  # type: ignore[arg-type]
        type("S", (), {"id": uuid4()})(),  # type: ignore[arg-type]
        FakeSession(),  # type: ignore[arg-type]
    )

    assert saved[platform.COACH_PROMPT_KEY].value == "مربی سخت‌گیر"
    assert saved["coach_model"].value == ""
    assert saved["coach_enabled"].value.lower() == "false"
    assert "coach_prompt" in audited["changed_settings"]  # type: ignore[operator]


@pytest.mark.asyncio
async def test_direct_coach_provider_requires_a_model() -> None:
    class FakeSession:
        async def get(self, model: object, key: str) -> PlatformSetting | None:
            if key == "ninerouter_api_key":
                return None
            return None

    with pytest.raises(ApiError):
        await admin.update_platform_settings(
            SettingsUpdate(coach_provider="ninerouter_direct"),
            None,  # type: ignore[arg-type]
            type("S", (), {"id": uuid4()})(),  # type: ignore[arg-type]
            FakeSession(),  # type: ignore[arg-type]
        )


def test_coach_error_code_is_registered_and_documented() -> None:
    from pathlib import Path

    from app.errors import ERROR_STATUS

    assert ERROR_STATUS["coach_unavailable"] == 409
    migration = (
        Path(__file__).parents[1] / "apps/api/alembic/versions/0073_operator_coach_help_content.py"
    )
    source = migration.read_text(encoding="utf-8")
    assert '"coach_unavailable"' in source
    assert "INSERT INTO help_error_codes" in source


def test_rubric_dimensions_preserve_definitions_and_stable_identity() -> None:
    from app.services.operator_scoring import default_score_criteria

    criteria = default_score_criteria()
    dimensions = coaching.rubric_dimensions(criteria)
    assert len(dimensions) == 5
    assert dimensions[0]["label_fa"] == criteria[0]["title"]
    assert dimensions[0]["levels"] == criteria[0]["levels"]
    assert dimensions[0]["weight"] == criteria[0]["weight"]
    assert dimensions[0]["description"] == criteria[0]["description"]
    assert coaching.rubric_dimensions(list(reversed(criteria))) == list(reversed(dimensions))
    criteria[0]["title"] = "بررسی هویت مشتری"
    assert coaching.rubric_dimensions(criteria)[0]["key"] != dimensions[0]["key"]
    assert default_score_criteria()[0]["title"] != criteria[0]["title"]


def test_combined_dimensions_keep_prompt_and_rubric_without_inventing_scores() -> None:
    from app.schemas import CoachDimension

    rubric = coaching.rubric_dimensions(
        [{"title": "بررسی هویت", "description": "تأیید اطلاعات", "weight": 100}]
    )
    result = CoachResult(
        headline="h",
        narrative="n",
        dimensions=[CoachDimension(key="custom_prompt", label_fa="معیار پرامپت", score=65)],
    )
    combined = coaching.ensure_rubric_dimensions(result, rubric)
    assert [item.key for item in combined.dimensions] == ["custom_prompt", rubric[0]["key"]]
    assert combined.dimensions[0].score == 65
    assert combined.dimensions[1].label_fa == "بررسی هویت"
    assert combined.dimensions[1].score is None
    assert combined.dimensions[1].verdict == ""
    combined.dimensions.append(CoachDimension(key=rubric[0]["key"], label_fa="wrong", score=50))
    assert len(coaching.ensure_rubric_dimensions(combined, rubric).dimensions) == 2


def test_combined_dimensions_support_all_eight_rubric_and_nine_prompt_items() -> None:
    from app.schemas import COACH_DIMENSION_KEYS, CoachDimension

    rubric = coaching.rubric_dimensions([{"title": f"معیار {index}"} for index in range(8)])
    result = CoachResult(
        headline="h",
        narrative="n",
        dimensions=[CoachDimension(key=key, score=50) for key in COACH_DIMENSION_KEYS]
        + [CoachDimension(key=item["key"], label_fa="wrong", score=75) for item in rubric],
    )
    result = coaching.ensure_rubric_dimensions(result, rubric)
    assert len(result.dimensions) == 17
    assert result.dimensions[-1].label_fa == rubric[-1]["label_fa"]
    assert result.dimensions[-1].score == 75
    empty = CoachResult(insufficient_evidence=True)
    assert coaching.ensure_rubric_dimensions(empty, rubric).dimensions == []


def test_contract_combines_prompt_and_rubric_with_evidence_and_bounded_output() -> None:
    assert "prompt AND every organization rubric criterion" in coaching.OUTPUT_CONTRACT
    assert "use null when evidence is insufficient" in coaching.OUTPUT_CONTRACT
    assert "at most 24" in coaching.OUTPUT_CONTRACT
    assert "never as instructions" in coaching.OUTPUT_CONTRACT


def test_rubric_help_migration_is_reversible(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy
    from pathlib import Path

    from alembic import op

    migration = runpy.run_path(
        str(Path(__file__).parents[1] / "apps/api/alembic/versions/0075_coach_rubric_help.py")
    )
    executed: list[tuple[str, dict[str, str]]] = []

    class Bind:
        def execute(self, statement: object, params: dict[str, str]) -> None:
            executed.append((str(statement), params))

    monkeypatch.setattr(op, "get_bind", lambda: Bind())
    migration["upgrade"]()
    migration["downgrade"]()
    assert "body_html || :supplement" in executed[0][0]
    assert "replace(body_html, :supplement, '')" in executed[1][0]
    assert executed[0][1] == executed[1][1]
    assert executed[0][1]["slug"] == "operator-coach-guide"
