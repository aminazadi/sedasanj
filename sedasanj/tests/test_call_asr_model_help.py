"""The call ASR model help migration extends the 0100 articles and restores them on downgrade."""

import importlib.util
from pathlib import Path

from app.errors import ERROR_STATUS
from app.services.help_content import sanitize_help_html

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"


def _load(filename: str):
    spec = importlib.util.spec_from_file_location(filename[:-3], VERSIONS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chain_has_one_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = VERSIONS.parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == ["0142_call_asr_model_help"]
    assert _load("0142_call_asr_model_help.py").down_revision == "0141_tenant_database_help"


def test_downgrade_text_matches_the_original_articles() -> None:
    module = _load("0142_call_asr_model_help.py")
    original = {row[0]: row[4] for row in _load("0100_call_asr_rollout.py").ARTICLES}
    assert original[module.SILERO_SLUG] == module.SILERO_OLD
    assert original[module.SETTINGS_SLUG] == module.SETTINGS_OLD


def test_new_text_names_the_setting_and_is_safe_html() -> None:
    module = _load("0142_call_asr_model_help.py")
    assert any("مدل تبدیل صدای تماس" in paragraph for paragraph in module.SILERO_NEW)
    assert any("Whisper" in paragraph for paragraph in module.SILERO_NEW)
    assert module.SILERO_NEW[0] == module.SILERO_OLD[0]
    for paragraphs in (module.SILERO_NEW, module.SETTINGS_NEW):
        body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
        cleaned, _ = sanitize_help_html(body)
        assert cleaned == body
    assert ERROR_STATUS["call_asr_settings_invalid"] == 422
