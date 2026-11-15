"""The output-types help migration: safe HTML and a help row for every new error code."""

import importlib.util
from pathlib import Path

from app.errors import ERROR_STATUS
from app.services.help_content import sanitize_help_html

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"


def _load():
    path = VERSIONS / "0148_jalase_output_types_help.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_articles_are_actionable_and_safe() -> None:
    for _slug, _title, _summary, body, code, action in _load().ARTICLES:
        cleaned, plain = sanitize_help_html(body)
        assert code in plain and action and "<ol>" in cleaned
        assert "<script" not in cleaned


def test_every_documented_code_is_a_real_api_error() -> None:
    module = _load()
    codes = [row[4] for row in module.ARTICLES] + [row[0] for row in module.EXTRA_CODES]
    assert {"output_type_invalid", "output_type_code_taken"} <= set(codes)
    for code in codes:
        assert code in ERROR_STATUS


def test_chain_links_to_the_types_migration() -> None:
    assert _load().down_revision == "0147_jalase_output_types"
