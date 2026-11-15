"""The Jalase-Negar plans help article is well-formed and the migration chain stays linear."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.services.help_content import sanitize_help_html

VERSIONS = Path(__file__).parents[1] / "apps/api/alembic/versions"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_article_is_actionable_and_safe() -> None:
    module = _load("0151_jalase_plans_help")
    for slug, _title, _summary, body in module.ARTICLES:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug)
        cleaned, plain = sanitize_help_html(body)
        assert "<ol>" in cleaned and re.search(r"[؀-ۿ]", plain)
        assert "ساعت" in plain and "توکن" in plain


def test_migration_chain_is_linear() -> None:
    assert _load("0150_jalase_plans_tokens").down_revision == "0149_meeting_documents"
    assert _load("0151_jalase_plans_help").down_revision == "0150_jalase_plans_tokens"


def test_seeded_plans_match_the_agreed_prices() -> None:
    plans = {row[0]: row[3] for row in _load("0150_jalase_plans_tokens").PLANS}
    assert plans == {"jn_bronze": 280_000, "jn_silver": 480_000, "jn_gold": 680_000}
