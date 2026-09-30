from __future__ import annotations

import pytest

from app.config import Settings
from worker_asr import main as asr_main
from worker_llm import main as llm_main


@pytest.mark.asyncio
async def test_asr_startup_defers_remote_engine_until_db_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="development",
        asr_engine="voicesanj",
        voicesanj_api_key=None,
        worker_metrics_port=0,
    )
    monkeypatch.setattr(asr_main, "get_settings", lambda: settings)
    monkeypatch.setattr(asr_main, "configure_logging", lambda *args: None)
    monkeypatch.setattr(asr_main, "start_metrics_server", lambda *args: None)

    def unexpected_build(_settings: Settings) -> object:
        raise AssertionError("remote engine must not be built from env-only startup settings")

    monkeypatch.setattr(asr_main, "build_engine", unexpected_build)
    ctx: dict[str, object] = {}

    await asr_main.startup(ctx)

    assert ctx["engine"] is None


@pytest.mark.asyncio
async def test_llm_startup_defers_http_client_until_db_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="development",
        llm_client="voicesanj",
        voicesanj_api_key=None,
        worker_metrics_port=0,
    )
    monkeypatch.setattr(llm_main, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_main, "configure_logging", lambda *args: None)
    monkeypatch.setattr(llm_main, "start_metrics_server", lambda *args: None)

    def unexpected_build(_settings: Settings) -> object:
        raise AssertionError("HTTP client must not be built from env-only startup settings")

    monkeypatch.setattr(llm_main, "build_client", unexpected_build)
    ctx: dict[str, object] = {}

    await llm_main.startup(ctx)

    assert ctx["client"] is None
