from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.routers.kpi import KpiSettingsIn, _funnel_rows, _is_opportunity, _rate, _rate_with_change
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
