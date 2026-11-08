"""The local-model assistant help migration is well formed and covers its error codes."""

import importlib.util
import re
from pathlib import Path

from app.errors import ERROR_STATUS
from app.services.help_content import sanitize_help_html

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"


def _migration():
    spec = importlib.util.spec_from_file_location(
        "m0124", VERSIONS / "0124_local_model_assistant_help.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_articles_are_sound() -> None:
    module = _migration()
    assert module.down_revision == "0123_footer_address_help"
    assert (VERSIONS / f"{module.down_revision}.py").exists() or any(
        module.down_revision in path.read_text() for path in VERSIONS.glob("0123*.py")
    )
    for slug, _title, _summary, body, code, _severity, _quick in module.ARTICLES:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug)
        cleaned, _ = sanitize_help_html(body)
        assert cleaned.count("<li>") == body.count("<li>")
        assert code in body


def test_new_api_error_code_has_a_status() -> None:
    assert ERROR_STATUS["assistant_model_no_tools"] == 422
