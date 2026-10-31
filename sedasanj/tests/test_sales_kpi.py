from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.routers.kpi import (
    KpiSettingsIn,
    _display_funnel,
    _funnel_rows,
    _is_opportunity,
    _missed_peak,
    _operator_quality_drops,
    _rate,
    _rate_with_change,
    _satisfaction_counts,
    _tenant_zone,
)
from app.schemas import ExtractionResult


def _base_extraction() -> dict[str, object]:
    return {
        "summary": "خلاصه",
        "keywords": [],
        "sentiment": {"overall": "neutral", "score": 0.5, "phrases": []},
        "intent": "sales_inquiry",
        "ner": {},
        "action_items": [],
        "topics": [],
    }


def test_sales_extraction_defaults_to_unknown_for_legacy_results() -> None:
    result = ExtractionResult.model_validate(_base_extraction())
    assert result.sales.outcome == "unknown"
    assert result.sales.certainty == "unknown"
    assert result.sales.confidence == 0


def test_sales_extraction_keeps_explicit_evidence() -> None:
    payload = _base_extraction()
    payload["sales"] = {
        "funnel_stage": "won",
        "outcome": "won",
        "certainty": "explicit",
        "confidence": 0.94,
        "product": "پلن سازمانی",
        "objections": ["price"],
        "evidence": [{"text": "خرید را نهایی می‌کنم", "t_start_ms": 1200, "t_end_ms": 2600}],
    }
    result = ExtractionResult.model_validate(payload)
    assert result.sales.outcome == "won"
    assert result.sales.evidence[0].t_start_ms == 1200


def test_sales_extraction_rejects_invalid_confidence() -> None:
    payload = _base_extraction()
    payload["sales"] = {"confidence": 1.2}
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(payload)


def test_rate_exposes_numerator_denominator_and_empty_state() -> None:
    assert _rate(3, 12) == {"value": 25.0, "numerator": 3, "denominator": 12}
    assert _rate(0, 0)["value"] is None


def test_rate_change_is_percentage_point_change() -> None:
    assert _rate_with_change(3, 10, 2, 10) == {
        "value": 30.0,
        "numerator": 3,
        "denominator": 10,
        "previous_value": 20.0,
        "change": 10.0,
    }


def test_ai_opportunity_excludes_not_qualified_and_accepts_sales_intent() -> None:
    insight = SimpleNamespace(intent="sales_inquiry")
    qualified = SimpleNamespace(outcome="interested", funnel_stage="unknown")
    rejected = SimpleNamespace(outcome="not_qualified", funnel_stage="qualified")
    assert _is_opportunity(insight, qualified) is True
    assert _is_opportunity(insight, rejected) is False


def test_funnel_uses_cumulative_reach_and_separate_lost_terminal() -> None:
    rows = [
        (
            SimpleNamespace(duration_ms=20000),
            None,
            SimpleNamespace(outcome="won", funnel_stage="won"),
        ),
        (
            SimpleNamespace(duration_ms=20000),
            None,
            SimpleNamespace(outcome="follow_up", funnel_stage="follow_up"),
        ),
        (
            SimpleNamespace(duration_ms=20000),
            None,
            SimpleNamespace(outcome="lost", funnel_stage="lost"),
        ),
    ]
    funnel = _funnel_rows(
        rows, ["effective", "qualified", "interested", "follow_up", "proposal", "won", "lost"]
    )
    values = {item["key"]: item for item in funnel}
    assert values["qualified"]["count"] == 3
    assert values["follow_up"]["count"] == 2
    assert values["won"]["count"] == 1
    assert values["lost"]["count"] == 1
    assert values["lost"]["drop_rate"] is None


def test_display_funnel_only_uses_nested_stage_denominators() -> None:
    funnel = _display_funnel([("all_calls", 20), ("effective", 12), ("opportunities", 6)])
    assert funnel[0]["pass_rate"] is None
    assert funnel[1]["pass_rate"] == 60.0
    assert funnel[2]["drop_rate"] == 50.0


def test_kpi_settings_reject_out_of_range_thresholds() -> None:
    with pytest.raises(ValidationError):
        KpiSettingsIn(
            follow_up_sla_hours=24,
            minimum_sample_size=5,
            probable_confidence_threshold=1.1,
            hot_opportunity_threshold=0.8,
            taxonomy_version=1,
            funnel_stages=["effective", "qualified", "won", "lost"],
            objection_taxonomy=["price"],
        )


def test_kpi_settings_reject_unknown_or_duplicate_taxonomy_values() -> None:
    with pytest.raises(ValidationError):
        KpiSettingsIn(
            follow_up_sla_hours=24,
            minimum_sample_size=5,
            probable_confidence_threshold=0.65,
            hot_opportunity_threshold=0.8,
            taxonomy_version=2,
            funnel_stages=["effective", "qualified", "won", "lost", "custom"],
            objection_taxonomy=["price"],
        )
    with pytest.raises(ValidationError):
        KpiSettingsIn(
            follow_up_sla_hours=24,
            minimum_sample_size=5,
            probable_confidence_threshold=0.65,
            hot_opportunity_threshold=0.8,
            taxonomy_version=2,
            funnel_stages=["effective", "qualified", "won", "lost"],
            objection_taxonomy=["price", "price"],
        )


def test_kpi_settings_accepts_known_dashboard_widgets_and_rejects_unknown_ones() -> None:
    payload = {
        "follow_up_sla_hours": 24,
        "minimum_sample_size": 5,
        "probable_confidence_threshold": 0.65,
        "hot_opportunity_threshold": 0.8,
        "taxonomy_version": 2,
        "funnel_stages": ["effective", "qualified", "won", "lost"],
        "objection_taxonomy": ["price"],
    }
    assert KpiSettingsIn(**payload, dashboard_widgets=["trend", "sentiment"]).dashboard_widgets == [
        "trend",
        "sentiment",
    ]
    assert "tasks" in KpiSettingsIn(**payload).dashboard_widgets
    with pytest.raises(ValidationError):
        KpiSettingsIn(**payload, dashboard_widgets=["trend", "unknown"])


def test_satisfaction_counts_only_known_sentiments() -> None:
    rows = [
        (None, SimpleNamespace(sentiment=value), None)
        for value in ("happy", "satisfied", "neutral", "angry", None)
    ] + [(None, None, None)]
    assert _satisfaction_counts(rows) == (2, 4)
    assert _rate_with_change(*_satisfaction_counts(rows), 0, 0)["value"] == 50.0


def test_missed_peak_uses_tenant_local_hour_and_thresholds() -> None:
    tehran = ZoneInfo("Asia/Tehran")
    # 2026-10-31 is a Saturday; 06:45 UTC is 10:15 in Tehran.
    slot = datetime(2026, 10, 31, 6, 45, tzinfo=UTC)
    other = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    answered = [slot] * 7 + [other] * 30
    missed = [slot] * 3 + [other] * 2
    peak = _missed_peak(answered, missed, tehran)
    assert peak == {"weekday": 5, "hour": 10, "missed": 3, "total": 10, "rate": 30.0}
    # Too few calls in the slot: no alert.
    assert _missed_peak([slot] * 5, [slot] * 3, tehran) is None
    # Below the unanswered-rate threshold: no alert.
    assert _missed_peak([slot] * 18, [slot] * 2, tehran) is None


def test_missed_peak_ties_prefer_more_unanswered_calls() -> None:
    tehran = ZoneInfo("Asia/Tehran")
    first = datetime(2026, 10, 31, 6, 0, tzinfo=UTC)
    second = first + timedelta(hours=2)
    peak = _missed_peak([first] * 8 + [second] * 16, [first] * 2 + [second] * 4, tehran)
    assert peak is not None and peak["missed"] == 4


def test_operator_quality_drops_need_sample_and_ten_points() -> None:
    operators = [
        {
            "operator_id": "a",
            "operator_label": "A",
            "quality_score": 61.0,
            "sample_sufficient": True,
        },
        {
            "operator_id": "b",
            "operator_label": "B",
            "quality_score": 70.0,
            "sample_sufficient": True,
        },
        {
            "operator_id": "c",
            "operator_label": "C",
            "quality_score": 50.0,
            "sample_sufficient": False,
        },
        {
            "operator_id": "d",
            "operator_label": "D",
            "quality_score": None,
            "sample_sufficient": True,
        },
        {
            "operator_id": "e",
            "operator_label": "E",
            "quality_score": 40.0,
            "sample_sufficient": True,
        },
    ]
    previous = {"a": 76.0, "b": 75.0, "c": 90.0, "d": 90.0}
    drops = _operator_quality_drops(operators, previous)
    assert [item["operator_id"] for item in drops] == ["a"]
    assert drops[0]["previous_value"] == 76.0


def test_tenant_zone_falls_back_to_tehran() -> None:
    assert _tenant_zone("Europe/Berlin").key == "Europe/Berlin"
    assert _tenant_zone("Not/AZone").key == "Asia/Tehran"
    assert _tenant_zone(None).key == "Asia/Tehran"


def test_executive_dashboard_help_article_is_well_formed() -> None:
    import importlib.util
    import re
    from pathlib import Path

    from app.services.help_content import sanitize_help_html

    path = (
        Path(__file__).parents[1]
        / "apps/api/alembic/versions/0074_executive_dashboard_help_content.py"
    )
    spec = importlib.util.spec_from_file_location("dashboard_help_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0073_operator_coach_help_content"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", module.ARTICLE_SLUG)
    for heading in ("نشانه‌ها", "علت", "رفع مشکل", "تأیید رفع مشکل", "پیشگیری"):
        assert f"<h2>{heading}</h2>" in module.ARTICLE_BODY
    safe_html, _ = sanitize_help_html(module.ARTICLE_BODY)
    assert safe_html == module.ARTICLE_BODY
