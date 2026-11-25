"""The call-metadata error codes have a Persian help article with an actionable fix."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from app.services.help_content import sanitize_help_html

MIGRATION = Path(__file__).parents[1] / "apps/api/alembic/versions/0163_call_metadata_help.py"


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("call_metadata_help_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_extends_the_current_head(migration: ModuleType) -> None:
    assert migration.down_revision == "0162_jalase_meeting_delete_help"
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", migration.SLUG)


def test_article_covers_both_codes_and_the_recovery_command(migration: ModuleType) -> None:
    assert migration.CODES == ("SS-UPL-1001", "SS-UPL-1004")
    assert re.search(r"[؀-ۿ]", migration.BODY)
    assert re.search(r"[؀-ۿ]", migration.TITLE)
    for code in migration.CODES:
        assert code in migration.BODY
    assert "recover-unresolved.php" in migration.BODY
    assert "failed/" in migration.BODY


def test_article_survives_the_shared_sanitizer(migration: ModuleType) -> None:
    cleaned, _plain = sanitize_help_html(migration.BODY)
    assert cleaned.count("<li>") == migration.BODY.count("<li>")
    assert "<script" not in cleaned.lower()


def test_upgrade_and_downgrade_bind_every_value(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    statements: list[tuple[str, dict]] = []

    class Bind:
        def execute(self, statement, params=None):
            statements.append((str(statement), params or {}))
            return self

    monkeypatch.setattr(migration.op, "get_bind", lambda: Bind())
    migration.upgrade()
    assert len([s for s in statements if "INTO help_articles" in s[0]]) == 1
    assert len([s for s in statements if "INTO help_error_codes" in s[0]]) == len(migration.CODES)
    assert all(";" not in sql for sql, _ in statements)

    statements.clear()
    migration.downgrade()
    assert len([s for s in statements if "DELETE FROM help_error_codes" in s[0]]) == 1
    assert len([s for s in statements if "DELETE FROM help_articles" in s[0]]) == 1
