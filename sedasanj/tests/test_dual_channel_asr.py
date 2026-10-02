from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.audio import AudioPreprocessingConfig, AudioPreprocessingError
from app.services.platform import mask_api_key, normalize_api_key, settings_public_view
from worker_asr.engine import AsrSegment, build_engine
from worker_asr.main import _engine_for_job, _transcribe_tracks


def test_mask_api_key() -> None:
    assert mask_api_key("") == ""
    assert mask_api_key("abcd") == "••••"
    assert mask_api_key("sk-live-secret-9999") == "••••9999"
    assert mask_api_key('"sk-live-secret-9999"') == "••••9999"


def test_normalize_api_key_strips_quotes_and_bearer() -> None:
    assert normalize_api_key(None) == ""
    assert normalize_api_key('  "secret-key"  ') == "secret-key"
    assert normalize_api_key("'secret-key'") == "secret-key"
    assert normalize_api_key("Bearer secret-key") == "secret-key"
    assert normalize_api_key('Bearer "secret-key"') == "secret-key"


@pytest.mark.asyncio
async def test_resolve_provider_settings_ignores_env_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings
    from app.services import platform as platform_service

    monkeypatch.setattr(
        platform_service,
        "get_settings",
        lambda: Settings(
            environment="development",
            asr_engine="voicesanj",
            llm_client="voicesanj",
            voicesanj_api_key="env-should-be-ignored",
            openai_api_key="env-openai-ignored",
        ),
    )

    class _Result:
        def scalars(self) -> list[object]:
            return []

        def scalar_one_or_none(self) -> None:
            return None

    class FakeSession:
        async def execute(self, statement: object) -> _Result:
            return _Result()

        async def get(self, model: object, key: object) -> None:
            return None

    runtime = await platform_service.resolve_provider_settings(FakeSession())  # type: ignore[arg-type]
    assert runtime.voicesanj_api_key is None
    assert runtime.openai_api_key is None


@pytest.mark.asyncio
async def test_resolve_provider_settings_uses_db_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings
    from app.services import platform as platform_service

    monkeypatch.setattr(
        platform_service,
        "get_settings",
        lambda: Settings(
            environment="development",
            asr_engine="voicesanj",
            llm_client="voicesanj",
            voicesanj_api_key="env-should-be-ignored",
        ),
    )

    row = type("Row", (), {"key": "api_key", "value": '"db-secret"'})()

    class _Result:
        def scalars(self) -> list[object]:
            return [row]

    class FakeSession:
        async def execute(self, statement: object) -> _Result:
            return _Result()

        async def get(self, model: object, key: object) -> None:
            return None

    runtime = await platform_service.resolve_provider_settings(FakeSession())  # type: ignore[arg-type]
    assert runtime.voicesanj_api_key == "db-secret"
    assert runtime.openai_api_key == "db-secret"


@pytest.mark.asyncio
async def test_resolve_provider_settings_switches_llm_to_voicesanj(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings
    from app.services import platform as platform_service

    monkeypatch.setattr(
        platform_service,
        "get_settings",
        lambda: Settings(environment="development", llm_client="llama"),
    )
    rows = [
        type("Row", (), {"key": "llm_provider", "value": "voicesanj"})(),
        type("Row", (), {"key": "api_key", "value": "shared-secret"})(),
        type("Row", (), {"key": "voicesanj_base_url", "value": "https://provider.test"})(),
        type("Row", (), {"key": "llm_model", "value": "analysis-model"})(),
        type("Row", (), {"key": "chat_model", "value": "chat-model"})(),
    ]

    class _Result:
        def scalars(self) -> list[object]:
            return rows

    class FakeSession:
        async def execute(self, statement: object) -> _Result:
            return _Result()

    runtime = await platform_service.resolve_provider_settings(FakeSession())  # type: ignore[arg-type]

    assert runtime.llm_client == "voicesanj"
    assert runtime.voicesanj_api_key == "shared-secret"
    assert runtime.voicesanj_base_url == "https://provider.test"
    assert runtime.voicesanj_llm_model == "analysis-model"


@pytest.mark.asyncio
async def test_legacy_admin_api_key_selects_voicesanj_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings
    from app.services import platform as platform_service

    monkeypatch.setattr(
        platform_service,
        "get_settings",
        lambda: Settings(environment="development", llm_client="llama"),
    )
    rows = [type("Row", (), {"key": "api_key", "value": "legacy-secret"})()]

    class _Result:
        def scalars(self) -> list[object]:
            return rows

    class FakeSession:
        async def execute(self, statement: object) -> _Result:
            return _Result()

    runtime = await platform_service.resolve_provider_settings(FakeSession())  # type: ignore[arg-type]

    assert runtime.llm_client == "voicesanj"


@pytest.mark.asyncio
async def test_resolve_provider_settings_routes_9router_through_aiservice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings
    from app.services import platform as platform_service

    monkeypatch.setattr(
        platform_service,
        "get_settings",
        lambda: Settings(
            environment="development",
            asr_engine="voicesanj",
            llm_client="voicesanj",
        ),
    )
    rows = [
        type("Row", (), {"key": "asr_provider", "value": "openai_compatible"})(),
        type("Row", (), {"key": "asr_route", "value": "ninerouter"})(),
        type(
            "Row",
            (),
            {"key": "asr_base_url", "value": "https://router.sedasanj.ir/"},
        )(),
        type("Row", (), {"key": "asr_api_key", "value": 'Bearer "router-secret"'})(),
        type("Row", (), {"key": "asr_model", "value": "openai/whisper-1"})(),
        type("Row", (), {"key": "analysis_route", "value": "ninerouter"})(),
        type("Row", (), {"key": "chat_route", "value": "ninerouter"})(),
        type("Row", (), {"key": "decision_route", "value": "ninerouter"})(),
        type("Row", (), {"key": "ninerouter_asr_prompt", "value": "asr"})(),
        type("Row", (), {"key": "ninerouter_analysis_prompt", "value": "analysis"})(),
        type("Row", (), {"key": "ninerouter_chat_prompt", "value": "chat"})(),
        type("Row", (), {"key": "ninerouter_decision_prompt", "value": "decision"})(),
        type("Row", (), {"key": "api_key", "value": "voicesanj-secret"})(),
    ]

    class _Result:
        def scalars(self) -> list[object]:
            return rows

    class FakeSession:
        async def execute(self, statement: object) -> _Result:
            return _Result()

    runtime = await platform_service.resolve_provider_settings(FakeSession())  # type: ignore[arg-type]

    assert runtime.asr_engine == "voicesanj"
    assert runtime.whisper_model == "openai/whisper-1"
    assert runtime.asr_provider_base_url == "https://aiservice.voicesanj.ir"
    assert runtime.asr_provider_api_key == "voicesanj-secret"
    assert runtime.aiservice_asr_path == "/v1/audio/transcriptions"
    assert runtime.aiservice_analysis_path == "/v1/ninerouter/chat/completions"
    assert runtime.ninerouter_asr_prompt == "asr"
    assert runtime.ninerouter_analysis_prompt == "analysis"
    assert runtime.ninerouter_chat_prompt == "chat"
    assert runtime.ninerouter_decision_prompt == "decision"
    assert runtime.voicesanj_api_key == "voicesanj-secret"


@pytest.mark.asyncio
async def test_resolve_provider_settings_uses_admin_audio_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings
    from app.services import platform as platform_service

    monkeypatch.setattr(
        platform_service,
        "get_settings",
        lambda: Settings(environment="development"),
    )
    rows = [
        type("Row", (), {"key": "audio_preprocessing_enabled", "value": "true"})(),
        type(
            "Row",
            (),
            {"key": "audio_denoiser_model", "value": "speech-afftdn-strong"},
        )(),
        type(
            "Row",
            (),
            {"key": "audio_enhancement_model", "value": "speech-clarity-strong"},
        )(),
    ]

    class _Result:
        def scalars(self) -> list[object]:
            return rows

    class FakeSession:
        async def execute(self, statement: object) -> _Result:
            return _Result()

    runtime = await platform_service.resolve_provider_settings(FakeSession())  # type: ignore[arg-type]
    assert runtime.audio_preprocessing_enabled is True
    assert runtime.audio_denoiser_model == "speech-afftdn-strong"
    assert runtime.audio_enhancement_model == "speech-clarity-strong"


@pytest.mark.asyncio
async def test_settings_view_exposes_server_owned_audio_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings
    from app.services import platform as platform_service

    monkeypatch.setattr(
        platform_service,
        "get_settings",
        lambda: Settings(environment="development"),
    )

    class _Result:
        def scalars(self) -> list[object]:
            return []

        def scalar_one_or_none(self) -> None:
            return None

    class FakeSession:
        async def execute(self, statement: object) -> _Result:
            return _Result()

        async def get(self, model: object, key: object) -> None:
            return None

    payload = await settings_public_view(FakeSession())  # type: ignore[arg-type]
    denoisers = payload["audio_denoiser_models"]
    enhancements = payload["audio_enhancement_models"]
    assert isinstance(denoisers, list)
    assert isinstance(enhancements, list)
    assert {row["id"] for row in denoisers} == {
        "none",
        "speech-afftdn-balanced",
        "speech-afftdn-strong",
    }
    assert {row["id"] for row in enhancements} == {
        "none",
        "speech-clarity-balanced",
        "speech-clarity-strong",
    }


@pytest.mark.asyncio
async def test_engine_job_rejects_corrupt_persisted_audio_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings

    base = Settings(environment="development", asr_engine="fixture")
    corrupt = base.model_copy(update={"audio_denoiser_model": "unknown"})

    async def fake_runtime(session: object) -> Settings:
        return corrupt

    monkeypatch.setattr("worker_asr.main.get_settings", lambda: base)
    monkeypatch.setattr("worker_asr.main.resolve_provider_settings", fake_runtime)
    ctx = {"engine": build_engine(base)}
    with pytest.raises(AudioPreprocessingError, match="unsupported denoiser"):
        await _engine_for_job(ctx, object())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dual_channel_transcribes_in_parallel(tmp_path: Path) -> None:
    original = tmp_path / "stereo.wav"
    original.write_bytes(b"RIFF")
    started = 0
    max_inflight = 0
    inflight = 0

    class FakeEngine:
        model_name = "test"
        model_version = "v1"

        async def transcribe(self, path: Path) -> list[AsrSegment]:
            nonlocal started, max_inflight, inflight
            started += 1
            inflight += 1
            max_inflight = max(max_inflight, inflight)
            import asyncio

            await asyncio.sleep(0.05)
            inflight -= 1
            return [AsrSegment(t_start_ms=0, t_end_ms=1000, text=path.stem)]

    async def fake_split(source: Path, left_out: Path, right_out: Path) -> None:
        left_out.write_bytes(b"L")
        right_out.write_bytes(b"R")

    with patch("worker_asr.main.split_channels", fake_split):
        rows = await _transcribe_tracks(FakeEngine(), original, tmp_path, channels=2)

    assert started == 2
    assert max_inflight == 2
    assert {channel for channel, _ in rows} == {0, 1}
    assert {segment.text for _, segment in rows} == {"left", "right"}


@pytest.mark.asyncio
async def test_dual_channel_sends_preprocessed_files_to_asr(tmp_path: Path) -> None:
    original = tmp_path / "stereo.wav"
    original.write_bytes(b"RIFF")
    received: list[str] = []

    class FakeEngine:
        model_name = "test"
        model_version = "v1"

        async def transcribe(self, path: Path) -> list[AsrSegment]:
            received.append(path.name)
            assert path.read_bytes() == b"processed"
            return [AsrSegment(t_start_ms=0, t_end_ms=1000, text=path.stem)]

    async def fake_split(source: Path, left_out: Path, right_out: Path) -> None:
        left_out.write_bytes(b"left-raw")
        right_out.write_bytes(b"right-raw")

    async def fake_preprocess(
        source: Path, target: Path, config: AudioPreprocessingConfig
    ) -> None:
        assert config.enabled is True
        assert source.read_bytes() in {b"left-raw", b"right-raw"}
        target.write_bytes(b"processed")

    config = AudioPreprocessingConfig(
        enabled=True,
        denoiser_model="speech-afftdn-balanced",
        enhancement_model="speech-clarity-balanced",
    )
    with (
        patch("worker_asr.main.split_channels", fake_split),
        patch("worker_asr.main.preprocess_mono_audio", fake_preprocess),
    ):
        await _transcribe_tracks(FakeEngine(), original, tmp_path, channels=2, preprocessing=config)

    assert set(received) == {"left-preprocessed.wav", "right-preprocessed.wav"}
