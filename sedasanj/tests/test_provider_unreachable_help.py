"""The parked-provider error codes have help articles and are chained after the usage ledger."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services.help_content import sanitize_help_html

VERSIONS = Path(__file__).parents[1] / "apps/api/alembic/versions"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "provider_unreachable_help", VERSIONS / "0126_provider_unreachable_help.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codes_and_chain() -> None:
    module = _load()
    assert module.down_revision == "0125_ai_usage_events"
    assert {item[3] for item in module.ARTICLES} == {
        "asr_provider_unreachable",
        "llm_provider_unreachable",
    }


def test_articles_are_sanitised_and_actionable() -> None:
    module = _load()
    for _slug, title, summary, code, quick in module.ARTICLES:
        body = module._BODY.format(code=code)
        cleaned, _plain = sanitize_help_html(body)
        assert cleaned.count("<li>") == body.count("<li>")
        assert code in body and title and summary and quick
        for heading in ("نشانه‌ها", "علت", "رفع مشکل", "تأیید رفع مشکل", "پیشگیری"):
            assert heading in body
