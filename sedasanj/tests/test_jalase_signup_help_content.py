"""The stand-alone Jalase-Negar error codes have status mappings and well-formed help."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from app.errors import ERROR_STATUS
from app.services.help_content import sanitize_help_html

VERSIONS = Path(__file__).parents[1] / "apps/api/alembic/versions"
CODES = {"jalase_signup_disabled", "bulk_action_too_large", "sms_template_missing"}


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "jalase_signup_help", VERSIONS / "0146_jalase_signup_help.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_code_has_a_status_and_a_help_row(migration: ModuleType) -> None:
    seeded = {row[4] for row in migration.ARTICLES} | {row[0] for row in migration.EXTRA_CODES}
    assert seeded == CODES
    assert set(ERROR_STATUS) >= CODES


def test_articles_are_actionable_and_safe(migration: ModuleType) -> None:
    for slug, _title, _summary, body, code, action in migration.ARTICLES:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug)
        cleaned, plain = sanitize_help_html(body)
        assert code in plain and action and "<ol>" in cleaned
        assert re.search(r"[؀-ۿ]", plain)


def test_chain_is_linear_after_the_free_plan_migration() -> None:
    first = VERSIONS / "0145_product_and_signup_channel.py"
    second = VERSIONS / "0146_jalase_signup_help.py"
    assert 'down_revision = "0144_site_scripts_help"' in first.read_text()
    assert 'down_revision = "0145_product_and_signup_channel"' in second.read_text()
