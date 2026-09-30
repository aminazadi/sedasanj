from __future__ import annotations

import json
from pathlib import Path

from app.schemas import ExtractionResult
from worker_llm.prompts import build_repair_request

PROMPTS = Path(__file__).resolve().parents[1] / "apps" / "worker_llm" / "prompts"


def test_prompt_file_exists_at_the_documented_path() -> None:
    assert (PROMPTS / "extract-fa-v1.txt").is_file()
    assert (PROMPTS / "extract-fa-v2.txt").is_file()
    assert (PROMPTS / "extract-fa-v3.txt").is_file()


def test_prompt_demands_json_only_and_lists_every_field() -> None:
    text = (PROMPTS / "extract-fa-v1.txt").read_text(encoding="utf-8")
    assert "JSON" in text
    for field in (
        "summary",
        "keywords",
        "sentiment.overall",
        "sentiment.score",
        "intent",
        "ner",
        "action_items",
        "topics",
    ):
        assert field in text


def test_v2_prompt_asks_for_per_channel_temporal_sentiment() -> None:
    text = (PROMPTS / "extract-fa-v2.txt").read_text(encoding="utf-8")
    for field in (
        "sentiment.caller.start",
        "sentiment.caller.end",
        "sentiment.caller.overall",
    ):
        assert field in text


def test_v3_prompt_asks_for_five_point_labels() -> None:
    text = (PROMPTS / "extract-fa-v3.txt").read_text(encoding="utf-8")
    for label in ("angry", "sad", "neutral", "satisfied", "happy"):
        assert label in text
    assert "عصبانی" in text
    assert "خوشحال" in text


def test_v3_prompt_example_matches_extraction_contract() -> None:
    text = (PROMPTS / "extract-fa-v3.txt").read_text(encoding="utf-8")
    example = json.loads("{" + text.split("\n{\n", 1)[1].split("\n}\n", 1)[0] + "}")
    result = ExtractionResult.model_validate(example)
    assert set(example) == {
        "summary", "keywords", "sentiment", "intent", "ner", "action_items", "topics", "sales"
    }
    assert set(example["ner"]) == {
        "persons", "dates", "amounts", "phone_numbers", "organizations"
    }
    assert set(example["sentiment"]) == {"overall", "score", "phrases", "caller", "agent"}
    assert set(example["sentiment"]["caller"]) == {"start", "end", "overall"}
    assert set(example["sentiment"]["agent"]) == {"start", "end", "overall"}
    assert result.sentiment.agent is not None
    assert result.sales.outcome == "unknown"


def test_repair_prompt_isolated_from_transcript_and_requires_exact_contract() -> None:
    system, user = build_repair_request('{"summary":"x"')
    assert "summary, keywords, sentiment, intent, ner, action_items, topics" in system
    assert '"agent": null' in system
    assert "<invalid_output>" in user
    assert user.rstrip().endswith("اکنون فقط شیء JSON معتبر را بنویس.")
