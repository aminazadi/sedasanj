"""Every billing API error code has a help page, and the seeded articles are well formed."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from app.errors import ERROR_STATUS
from app.services.help_content import sanitize_help_html

MIGRATION = Path(__file__).parents[1] / "apps/api/alembic/versions/0069_billing_help_content.py"
BILLING_CODES = {
    "subscription_exists",
    "change_conflict",
    "plan_not_sellable",
    "plan_in_use",
    "plan_code_exists",
    "order_amount_too_large",
    "subscription_inactive",
    "insufficient_credit",
    "quota_exceeded",
}


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("billing_help_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_billing_code_has_a_help_row_and_a_status(migration: ModuleType) -> None:
    seeded = {code for code, *_ in migration.ERRORS}
    assert seeded == BILLING_CODES
    assert set(ERROR_STATUS) >= BILLING_CODES


def test_slugs_are_dot_free_and_unique(migration: ModuleType) -> None:
    slugs = [slug for slug, *_ in migration.ARTICLES] + [
        migration._slug(c) for c, *_ in migration.ERRORS
    ]
    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug) for slug in slugs)


def test_error_articles_name_an_action_and_the_code(migration: ModuleType) -> None:
    for code, _title, _severity, cause, steps, quick in migration.ERRORS:
        blocks = migration.error_blocks(cause, steps, code)
        body_html, body_plain = migration._body(blocks)
        assert code in body_plain and steps and quick
        assert re.search(r"[؀-ۿ]", body_plain)
        cleaned, _plain = sanitize_help_html(body_html)
        assert "<ol>" in cleaned


def test_article_html_survives_the_shared_sanitizer(migration: ModuleType) -> None:
    for _slug, _title, _summary, blocks in migration.ARTICLES:
        body_html, _plain = migration._body(blocks)
        cleaned, _ = sanitize_help_html(body_html)
        assert cleaned.count("<li>") == body_html.count("<li>")
