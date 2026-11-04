"""Organization archive help seeds respect the database slug contract."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest


def test_help_slugs_links_and_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    directory = Path(__file__).parents[1] / "apps/api/alembic/versions"
    spec = importlib.util.spec_from_file_location(
        "organization_data_migration", directory / "0102_organization_data.py"
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = (directory / "0054_help_center.py").read_text()
    match = re.search(r"help_articles_slug_check CHECK \(slug ~ '([^']+)'\)", schema)
    assert match
    slug_pattern = match.group(1)

    calls: list[tuple[str, dict[str, Any]]] = []

    class Bind:
        def execute(self, statement: Any, parameters: dict[str, Any]) -> None:
            calls.append((str(statement), parameters))

    monkeypatch.setattr(migration.op, "get_bind", Bind)
    monkeypatch.setattr(migration.op, "execute", lambda statement: None)
    migration.upgrade()

    articles = {
        parameters["slug"]
        for statement, parameters in calls
        if "INSERT INTO help_articles" in statement
    }
    links = {
        parameters["code"]: parameters["slug"]
        for statement, parameters in calls
        if "INSERT INTO help_error_codes" in statement
    }
    assert len(articles) == len(migration.ERRORS) + 1
    assert all(re.fullmatch(slug_pattern, slug) for slug in articles)
    assert set(links) == set(migration.ERRORS)
    assert set(links.values()) == articles - {"organization-data-backup"}

    calls.clear()
    migration.downgrade()
    removed_articles = {
        parameters["slug"]
        for statement, parameters in calls
        if "DELETE FROM help_articles" in statement
    }
    removed_codes = {
        parameters["code"]
        for statement, parameters in calls
        if "DELETE FROM help_error_codes" in statement
    }
    assert removed_articles == set(links.values())
    assert removed_codes == set(links)
