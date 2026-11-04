from contextlib import asynccontextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.errors import ERROR_STATUS, ApiError
from app.services import call_retranscription, transcript_corrections
from app.services.audio import AudioPreprocessingConfig
from app.services.call_speakers import render_turns
from app.services.provider_errors import ASR_NO_SPEECH_DETAIL, ProviderError, classify_failure
from worker_asr import main
from worker_asr.engine import SHENAVA_CALL_MODEL, AsrSegment, VoiceSanjEngine


async def test_call_mode_overrides_provider_and_disables_preprocessing(monkeypatch) -> None:
    from app.services import platform

    monkeypatch.setattr(
        platform, "get_settings", lambda: Settings(audio_preprocessing_enabled=True)
    )
    monkeypatch.setattr(main, "build_engine", lambda settings: settings)
    tenant = SimpleNamespace(call_asr_mode="vad_segment", call_asr_profile="telephony")
    session = SimpleNamespace(
        get=AsyncMock(return_value=tenant),
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [])),
    )
    _, preprocessing, runtime = await main._engine_for_job(
        {}, session, "ninerouter_direct", "snapshot", uuid4()
    )
    assert runtime.call_asr_mode == "vad_segment"
    assert runtime.call_asr_profile == "telephony"
    assert runtime.active_ai_provider == "aiservice"
    assert runtime.voicesanj_asr_model != "snapshot"
    assert preprocessing.enabled is False


async def test_voice_engine_keeps_primary_on_both_channels_and_tracks_fallback(wav_file) -> None:
    settings = Settings(
        voicesanj_api_key="fixture",
        call_asr_mode="vad_segment",
        call_asr_profile="telephony",
        call_asr_telephony_threshold=0.41,
        call_asr_fallback_models=["fallback"],
        correction_audio_models=["unrelated-correction-model"],
        mono_diarization_enabled=True,
    )
    engine = VoiceSanjEngine(settings)
    engine._client.transcribe = AsyncMock(
        side_effect=[
            {"model": "fallback", "text": "سلام"},
            {
                "model": SHENAVA_CALL_MODEL,
                "segments": [
                    {
                        "start": 0.1,
                        "end": 0.6,
                        "text": "بفرمایید",
                        "timestamp_source": "silero_vad",
                    },
                ],
            },
        ]
    )
    left = await engine.transcribe(wav_file(), diarize=True)
    right = await engine.transcribe(wav_file())
    for request in engine._client.transcribe.await_args_list:
        assert request.kwargs["model"] == SHENAVA_CALL_MODEL
        assert request.kwargs["models"] == [SHENAVA_CALL_MODEL, "fallback"]
        assert request.kwargs["segmenter"] == "silero_vad"
        assert request.kwargs["engine_profile"] == "telephony"
        assert request.kwargs["silero_threshold"] == 0.41
        assert request.kwargs["diarize"] is False

    model, identity = main.call_asr_identity(
        [(0, left[0]), (1, right[0])], engine, settings, AudioPreprocessingConfig(enabled=False)
    )
    assert model == f"fallback+{SHENAVA_CALL_MODEL}"
    assert identity == (
        "ch0:fallback|preprocess:none|segmenter:legacy;"
        f"ch1:{SHENAVA_CALL_MODEL}|preprocess:none|segmenter:silero-vad"
        "|profile:telephony|threshold:0.41"
    )


async def test_one_silent_channel_does_not_drop_speech_or_mask_other_errors(
    monkeypatch,
    tmp_path,
) -> None:
    engine = SimpleNamespace(
        transcribe=AsyncMock(
            side_effect=[
                ProviderError("asr_no_speech", ASR_NO_SPEECH_DETAIL, retryable=False),
                [AsrSegment(200, 800, "سلام")],
            ]
        )
    )
    monkeypatch.setattr(main, "split_channels", AsyncMock())
    rows = await main._transcribe_tracks(engine, tmp_path / "call.wav", tmp_path, 2)
    assert [(channel, row.text) for channel, row in rows] == [(1, "سلام")]
    engine.transcribe.side_effect = [[], []]
    with pytest.raises(ProviderError) as error:
        await main._transcribe_tracks(engine, tmp_path / "call.wav", tmp_path, 2)
    assert classify_failure(error.value, kind="asr") == (
        "asr_no_speech",
        ASR_NO_SPEECH_DETAIL,
        False,
    )
    engine.transcribe.side_effect = [
        ProviderError("asr_no_speech", ASR_NO_SPEECH_DETAIL, retryable=False),
        RuntimeError("ASR model missing"),
    ]
    with pytest.raises(RuntimeError, match="model missing"):
        await main._transcribe_tracks(engine, tmp_path / "call.wav", tmp_path, 2)


async def test_corrected_text_keeps_outbound_labels_and_timestamps() -> None:
    tenant_id, call_id, revision_id = uuid4(), uuid4(), uuid4()
    session = SimpleNamespace(
        add=lambda row: None,
        get=AsyncMock(
            side_effect=[
                SimpleNamespace(direction="outbound"),
                SimpleNamespace(speaker_mode="dual_channel"),
            ]
        ),
    )
    transcript = SimpleNamespace(call_id=call_id, active_asr_revision_id=uuid4())
    revision = SimpleNamespace(id=revision_id, tenant_id=tenant_id, metrics=None)
    segments = [
        {
            "id": str(uuid4()),
            "channel": 0,
            "t_start_ms": 1000,
            "t_end_ms": 2000,
            "text": "سلام",
            "corrected_text": "سلام.",
            "uncertain": False,
        },
        {
            "id": str(uuid4()),
            "channel": 1,
            "t_start_ms": 3000,
            "t_end_ms": 5000,
            "text": "بفرمایید",
            "corrected_text": "بفرمایید.",
            "uncertain": False,
        },
    ]
    await transcript_corrections.activate_revision(
        session,
        transcript=transcript,
        revision=revision,
        segments=segments,
        uncertain_items=[],
        result={},
    )
    assert transcript.corrected_text == "[agent 00:01] سلام.\n[caller 00:03] بفرمایید."
    assert render_turns([(0, 0, "سلام")], "outbound", "mono_unknown") == "[speaker_1 00:00] سلام"


async def test_batch_stage_reuses_campaign_and_blocks_busy_call() -> None:
    found = SimpleNamespace(scalar_one_or_none=lambda: object())
    absent = SimpleNamespace(scalar_one_or_none=lambda: None)
    session = SimpleNamespace(get=AsyncMock(return_value=object()))
    call = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), audio_id=uuid4(), status="complete")
    session.execute = AsyncMock(side_effect=[found, absent])
    session.scalar = AsyncMock(side_effect=[None, uuid4()])
    assert await call_retranscription.stage(session, call, campaign="pilot-1") is None
    session.execute.side_effect = [found, found]
    with pytest.raises(ApiError) as error:
        await call_retranscription.stage(session, call)
    assert error.value.code == "call_retranscription_busy"


async def test_retranscription_reuses_unbilled_analysis_after_correction(monkeypatch) -> None:
    from worker_llm import correction

    run = SimpleNamespace(id=uuid4(), ai_provider="aiservice", result=None)
    call = SimpleNamespace(status="correcting")
    session = SimpleNamespace(
        get=AsyncMock(return_value=call),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: run)),
        add=lambda row: None,
        flush=AsyncMock(),
    )
    revision = SimpleNamespace(trigger="automatic", metrics={"previous_status": "failed_terminal"})

    @asynccontextmanager
    async def scope(_tenant):
        yield session

    stage = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(correction, "session_scope", scope)
    monkeypatch.setattr(correction.analysis_runs, "ensure_snapshot", AsyncMock())
    monkeypatch.setattr(correction.processing_events, "record", AsyncMock())
    monkeypatch.setattr(correction.outbox, "stage_job", stage)
    await correction._stage_analysis(tenant_id=uuid4(), call_id=uuid4(), revision=revision)
    assert stage.await_args.kwargs["reanalysis"] is True
    assert stage.await_args.kwargs["previous_status"] == "failed_terminal"
    assert run.result == {"_reanalysis": True, "_previous_status": "failed_terminal"}


async def test_retranscription_reuses_unbilled_analysis_after_emotion(monkeypatch) -> None:
    from worker_emotion import main as emotion

    call = SimpleNamespace(status="emotion_analyzing")
    run = SimpleNamespace(result={"_reanalysis": True, "_previous_status": "complete"})
    session = SimpleNamespace(
        get=AsyncMock(side_effect=[call, run]),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
        add=lambda row: None,
        flush=AsyncMock(),
    )

    @asynccontextmanager
    async def scope(_tenant):
        yield session

    stage = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(emotion, "session_scope", scope)
    monkeypatch.setattr(
        emotion,
        "resolve_provider_settings",
        AsyncMock(
            return_value=Settings(correction_enabled=False),
        ),
    )
    monkeypatch.setattr(emotion.processing_events, "record", AsyncMock())
    monkeypatch.setattr(emotion.outbox, "stage_job", stage)
    await emotion._stage_llm(
        tenant_id=uuid4(),
        call_id=uuid4(),
        analysis_run_id=uuid4(),
        message="",
    )
    assert stage.await_args.kwargs["reanalysis"] is True
    assert stage.await_args.kwargs["previous_status"] == "complete"


def test_asr_rollout_help_covers_all_new_errors(monkeypatch) -> None:
    path = (
        Path(__file__).resolve().parents[1] / "apps/api/alembic/versions/0100_call_asr_rollout.py"
    )
    spec = spec_from_file_location("call_asr_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    codes = {
        code
        for _, _, code, action, paragraphs in migration.ARTICLES
        if code and action and paragraphs
    }
    assert codes == {"asr_no_speech", "call_asr_settings_invalid", "call_retranscription_busy"}
    assert codes <= ERROR_STATUS.keys()
    assert Settings.model_fields["max_upload_bytes"].default == 512 * 1024 * 1024

    ddl = []
    dml = []
    monkeypatch.setattr(migration.op, "execute", ddl.append)
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(execute=lambda sql, params: dml.append((str(sql), params))),
    )
    migration.upgrade()
    assert len(ddl) == 3
    assert all(";" not in sql for sql in [*ddl, *(sql for sql, _ in dml)])
    assert {params["code"] for _, params in dml if "code" in params} == codes
    migration.downgrade()
    assert ddl[-3:] == [
        "ALTER TABLE asr_transcript_revisions DROP COLUMN asr_identity",
        "ALTER TABLE tenants DROP COLUMN call_asr_profile",
        "ALTER TABLE tenants DROP COLUMN call_asr_mode",
    ]
