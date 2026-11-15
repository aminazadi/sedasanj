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


def test_gamification_codes_have_statuses_and_a_safe_article() -> None:
    from app.errors import ERROR_STATUS

    module = _load("0153_jalase_gamification_help")
    assert _load("0152_jalase_gamification").down_revision == "0151_jalase_plans_help"
    assert module.down_revision == "0152_jalase_gamification"
    codes = {row[0] for row in module.CODES}
    assert codes == {"invite_invalid", "invite_not_allowed", "invite_disabled"}
    assert set(ERROR_STATUS) >= codes
    cleaned, plain = sanitize_help_html(module.BODY)
    assert "<ol>" in cleaned and all(code in plain for code in codes)
    assert all(action for _code, _summary, action in module.CODES)


def test_link_codes_have_statuses_and_a_safe_article() -> None:
    from app.errors import ERROR_STATUS

    module = _load("0155_jalase_links_help")
    assert _load("0154_jalase_account_links").down_revision == "0153_jalase_gamification_help"
    assert module.down_revision == "0154_jalase_account_links"
    codes = {row[0] for row in module.CODES}
    assert codes == {"link_invalid_target", "link_already_exists", "link_not_found"}
    assert set(ERROR_STATUS) >= codes
    cleaned, plain = sanitize_help_html(module.BODY)
    assert "<ol>" in cleaned and all(code in plain for code in codes)


def test_import_code_has_a_status_and_a_safe_help_paragraph() -> None:
    from app.errors import ERROR_STATUS

    module = _load("0156_jalase_import_help")
    assert module.down_revision == "0155_jalase_links_help"
    assert module.CODE in ERROR_STATUS
    cleaned, plain = sanitize_help_html(module.EXTRA)
    assert module.CODE in plain and "<script" not in cleaned
