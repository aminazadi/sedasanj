"""The sound-events help article migration is well formed and names its error code."""

import importlib.util
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"


def test_sound_events_help_article_migration_is_sound() -> None:
    from app.services.help_content import sanitize_help_html

    spec = importlib.util.spec_from_file_location(
        "m0121", VERSIONS / "0121_jalase_negar_sound_events_help.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0121_jalase_sound_events_help"
    assert module.down_revision == "0120_jalase_push"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", module.SLUG)
    body_html, body_plain = module._body()
    assert "JN-ASR-0002" in body_plain
    assert "[خنده]" in body_plain
    cleaned, _ = sanitize_help_html(body_html)
    assert cleaned.count("<li>") == body_html.count("<li>") == 5
