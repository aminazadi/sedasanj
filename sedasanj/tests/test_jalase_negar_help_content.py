"""Every Jalase-Negar release error code has a help page, and the seeded articles are sound."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from app.errors import ERROR_STATUS, RETRYABLE_CODES
from app.services.help_content import sanitize_help_html

MIGRATION = (
    Path(__file__).parents[1] / "apps/api/alembic/versions/0098_jalase_negar_update_help_content.py"
)
RELEASE_CODES = {
    "apk_invalid",
    "apk_inspection_unavailable",
    "release_version_conflict",
    "release_file_unavailable",
}


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("jalase_negar_help_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_release_code_has_a_status_and_a_help_row(migration: ModuleType) -> None:
    seeded = {code for code, *_ in migration.ERRORS}
    assert seeded == RELEASE_CODES
    assert set(ERROR_STATUS) >= RELEASE_CODES
    assert all(len(code) <= 40 for code in seeded)
    assert migration.down_revision == "0097_jalase_negar_releases"


def test_only_transient_codes_are_retryable() -> None:
    assert {"release_file_unavailable", "apk_inspection_unavailable"} <= RETRYABLE_CODES
    assert not {"apk_invalid", "release_version_conflict"} & RETRYABLE_CODES


def test_slugs_are_dot_free_and_unique(migration: ModuleType) -> None:
    slugs = [slug for slug, *_ in migration.ARTICLES] + [
        migration._slug(code) for code, *_ in migration.ERRORS
    ]
    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug) for slug in slugs)


def test_error_articles_name_an_action_and_the_code(migration: ModuleType) -> None:
    for code, _title, severity, cause, steps, quick in migration.ERRORS:
        assert severity in ("info", "warning", "error", "critical")
        body_html, body_plain = migration._body(migration.error_blocks(cause, steps, code))
        assert code in body_plain and steps and quick
        assert re.search(r"[؀-ۿ]", body_plain)
        cleaned, _ = sanitize_help_html(body_html)
        assert "<ol>" in cleaned


def test_articles_survive_the_sanitizer_and_explain_data_safety(migration: ModuleType) -> None:
    for _slug, _title, _summary, blocks in migration.ARTICLES:
        body_html, plain = migration._body(blocks)
        cleaned, _ = sanitize_help_html(body_html)
        assert cleaned.count("<li>") == body_html.count("<li>")
    guide = migration._body(migration.ARTICLES[0][3])[1]
    assert "پاک نمی‌شوند" in guide and "بعداً" in guide


def test_upgrade_binds_every_value(migration: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    statements: list[tuple[str, dict]] = []

    class Bind:
        def execute(self, statement, params=None):  # type: ignore[no-untyped-def]
            statements.append((str(statement), params or {}))
            return self

        def scalar_one(self) -> int:
            return 1

    monkeypatch.setattr(migration.op, "get_bind", lambda: Bind())
    migration.upgrade()
    assert len([s for s in statements if "INTO help_error_codes" in s[0]]) == 4
    assert all(";" not in sql for sql, _ in statements)
