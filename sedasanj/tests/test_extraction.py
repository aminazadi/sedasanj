from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.schemas import ExtractionResult, InsightsOut
from app.sentiment import delta_and_trajectory, valence
from worker_llm.main import extract_json

VALID = {
    "summary": "مشتری درباره قطعی اینترنت تماس گرفت و مشکل پیگیری شد.",
    "keywords": ["اینترنت", "قطعی", "پیگیری"],
    "sentiment": {
        "overall": "negative",
        "score": 0.8,
        "phrases": [{"text": "دو روز قطع بوده", "sentiment": "negative"}],
    },
    "intent": "technical_support",
    "ner": {"persons": ["علی"], "dates": ["فردا"], "amounts": [], "phone_numbers": []},
    "action_items": ["تماس مجدد فردا"],
    "topics": ["پشتیبانی"],
}

VALID_V2 = {
    **VALID,
    "sentiment": {
        "overall": "negative",
        "score": 0.8,
        "phrases": [{"text": "دو روز قطع بوده", "sentiment": "negative"}],
        "caller": {
            "start": {"label": "negative", "score": 0.9},
            "end": {"label": "positive", "score": 0.7},
            "overall": {"label": "neutral", "score": 0.4},
        },
        "agent": {
            "start": {"label": "neutral", "score": 0.5},
            "end": {"label": "positive", "score": 0.6},
            "overall": {"label": "positive", "score": 0.55},
        },
    },
}


def test_extract_json_accepts_plain_json() -> None:
    assert extract_json(json.dumps(VALID))["intent"] == "technical_support"


def test_extract_json_recovers_from_a_fenced_block() -> None:
    raw = "بله، خروجی:\n```json\n" + json.dumps(VALID) + "\n```\nپایان"
    assert extract_json(raw)["sentiment"]["overall"] == "negative"


def test_extract_json_recovers_from_leading_prose() -> None:
    raw = "این نتیجه تحلیل است: " + json.dumps(VALID)
    assert extract_json(raw)["summary"] == VALID["summary"]


def test_extract_json_ignores_braces_after_the_first_complete_object() -> None:
    raw = json.dumps(VALID) + "\nتوضیح اضافه {نامعتبر}"
    assert extract_json(raw)["intent"] == "technical_support"


def test_extract_json_repairs_missing_commas_between_fields() -> None:
    raw = json.dumps(VALID, ensure_ascii=False, indent=2)
    raw = raw.replace('  "intent":', '  "intent":', 1).replace(
        '  ],\n  "intent":', '  ]\n  "intent":', 1
    )
    assert extract_json(raw)["intent"] == "technical_support"


def test_extract_json_repairs_unescaped_quotes_in_a_string() -> None:
    raw = json.dumps(VALID, ensure_ascii=False)
    raw = raw.replace("قطعی اینترنت", 'قطعی "سراسری" اینترنت')
    assert extract_json(raw)["summary"].startswith('مشتری درباره قطعی "سراسری"')


def test_extract_json_repairs_a_trailing_object_comma() -> None:
    raw = json.dumps(VALID, ensure_ascii=False)
    raw = raw[:-1] + ",}"
    assert extract_json(raw)["intent"] == "technical_support"


def test_extract_json_repairs_a_trailing_array_comma() -> None:
    raw = json.dumps(VALID, ensure_ascii=False).replace(
        '"keywords": ["اینترنت", "قطعی", "پیگیری"]',
        '"keywords": ["اینترنت", "قطعی", "پیگیری",]',
    )
    assert extract_json(raw)["keywords"] == ["اینترنت", "قطعی", "پیگیری"]


def test_extract_json_raises_when_there_is_no_object() -> None:
    with pytest.raises(ValueError):
        extract_json("متن بدون هیچ ساختار JSON")


def test_schema_caps_keywords_and_topics_instead_of_failing() -> None:
    """An over-eager model must not cost the tenant a terminal failure (§9.2)."""
    payload = json.loads(json.dumps(VALID))
    payload["keywords"] = [f"k{index}" for index in range(9)]
    payload["topics"] = [f"t{index}" for index in range(7)]
    result = ExtractionResult.model_validate(payload)
    assert len(result.keywords) == 5
    assert len(result.topics) == 3


def test_schema_rejects_unknown_intent() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["intent"] = "buy_a_boat"
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(payload)


def test_schema_rejects_out_of_range_sentiment_score() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["sentiment"]["score"] = 4.2
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(payload)


def test_schema_accepts_persian_sentiment_and_phrase_alias() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["sentiment"] = {
        "overall": "مثبت",
        "score": 0.7,
        "phrases": [{"phrase": "خیلی ممنون", "sentiment": "مثبت"}],
    }
    result = ExtractionResult.model_validate(payload)
    assert result.sentiment.overall == "happy"
    assert result.sentiment.phrases[0].text == "خیلی ممنون"
    assert result.sentiment.phrases[0].sentiment == "happy"


def test_schema_accepts_five_point_persian_labels() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["sentiment"] = {
        "overall": "عصبانی",
        "score": 0.9,
        "phrases": [{"text": "دیگه تحمل ندارم", "sentiment": "ناراحت"}],
    }
    result = ExtractionResult.model_validate(payload)
    assert result.sentiment.overall == "angry"
    assert result.sentiment.phrases[0].sentiment == "sad"


def test_schema_accepts_object_shaped_top_level_sentiment() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["sentiment"] = {
        "overall": {"label": "neutral", "score": 0.6},
        "phrases": [],
        "caller": None,
        "agent": None,
    }

    result = ExtractionResult.model_validate(payload)

    assert result.sentiment.overall == "neutral"
    assert result.sentiment.score == 0.6
    assert result.sentiment.caller is not None
    assert result.sentiment.caller.overall.score == 0.6


def test_schema_keeps_explicit_score_with_object_shaped_overall() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["sentiment"]["overall"] = {"label": "satisfied", "score": 0.2}
    payload["sentiment"]["score"] = 0.8

    result = ExtractionResult.model_validate(payload)

    assert result.sentiment.overall == "satisfied"
    assert result.sentiment.score == 0.8


def test_schema_accepts_empty_ner_list() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["ner"] = []
    result = ExtractionResult.model_validate(payload)
    assert result.ner.persons == []


def test_schema_defaults_empty_entity_lists() -> None:
    payload = json.loads(json.dumps(VALID))
    payload.pop("ner")
    result = ExtractionResult.model_validate(payload)
    assert result.ner.organizations == []


def test_legacy_sentiment_synthesizes_caller_channel() -> None:
    result = ExtractionResult.model_validate(VALID)
    assert result.sentiment.caller is not None
    assert result.sentiment.caller.overall.label == "sad"
    assert result.sentiment.caller.trajectory == "stable"
    assert result.sentiment.agent is None
    profile = result.sentiment.profile()
    assert profile.voice is None
    assert profile.text.caller.overall.label == "sad"


def test_per_channel_start_end_overall_computes_delta() -> None:
    result = ExtractionResult.model_validate(VALID_V2)
    caller = result.sentiment.caller
    assert caller is not None
    assert caller.start.label == "sad"
    assert caller.end.label == "happy"
    assert caller.overall.label == "neutral"
    assert caller.trajectory == "improved"
    assert caller.delta > 0
    assert result.sentiment.overall == "neutral"
    assert result.sentiment.agent is not None
    assert result.sentiment.agent.overall.label == "happy"


def test_party_sentiment_accepts_string_points() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["sentiment"]["caller"] = {
        "start": "negative",
        "end": "negative",
        "overall": "negative",
    }
    result = ExtractionResult.model_validate(payload)
    assert result.sentiment.caller is not None
    assert result.sentiment.caller.start.score == 0.5
    assert result.sentiment.caller.trajectory == "stable"


def test_insights_legacy_rows_get_a_text_profile() -> None:
    out = InsightsOut(sentiment="positive", sentiment_score=0.8)
    assert out.sentiment_profile is not None
    assert out.sentiment_profile.text.caller.overall.label == "happy"
    assert out.sentiment_profile.voice is None


def test_valence_and_trajectory_helpers() -> None:
    assert valence("happy", 1.0) == 1.0
    assert valence("angry", 1.0) == 0.0
    assert valence("sad", 1.0) == 0.25
    assert valence("satisfied", 1.0) == 0.75
    assert valence("neutral", 0.9) == 0.5
    delta, trajectory = delta_and_trajectory("angry", 0.9, "happy", 0.8)
    assert delta > 0
    assert trajectory == "improved"
