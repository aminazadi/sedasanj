"""Locks the server side of the ASR parity contract (docs/asr-parity-contract.md).

The fixtures in tests/fixtures/asr_parity/ are shared with the on-device pipeline. If the server
changes a constant, a filter chain or a merge rule, these tests fail and the contract (and the
Jalase-Negar port) must be updated in the same change.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services import audio
from app.services.audio import (
    DEFAULT_MAX_GAIN_DB,
    DEFAULT_TARGET_LOUDNESS_LUFS,
    MAX_ATTENUATION_DB,
    MAX_GAIN_RANGE,
    NEGLIGIBLE_GAIN_DB,
    SILENT_CHANNEL_LUFS,
    TARGET_LOUDNESS_RANGE,
    AudioPreprocessingConfig,
    compute_gain_db,
)
from app.services.call_speakers import render_turns
from worker_asr.engine import AsrSegment
from worker_asr.main import TURN_MERGE_GAP_MS, consolidate_segments

FIXTURES = Path(__file__).parent / "fixtures" / "asr_parity"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


CONSTANTS = _load("constants.json")


def test_preprocessing_constants_match_the_contract() -> None:
    pre = CONSTANTS["preprocessing"]
    assert pre["target_loudness_lufs"] == DEFAULT_TARGET_LOUDNESS_LUFS
    assert list(TARGET_LOUDNESS_RANGE) == pre["target_loudness_range_lufs"]
    assert pre["max_gain_db"] == DEFAULT_MAX_GAIN_DB
    assert list(MAX_GAIN_RANGE) == pre["max_gain_range_db"]
    assert pre["max_attenuation_db"] == MAX_ATTENUATION_DB
    assert pre["silent_channel_lufs"] == SILENT_CHANNEL_LUFS
    assert pre["negligible_gain_db"] == NEGLIGIBLE_GAIN_DB


def test_platform_defaults_match_the_contract() -> None:
    fields = Settings.model_fields
    pre = CONSTANTS["preprocessing"]
    assert fields["audio_preprocessing_enabled"].default is pre["enabled_by_default"]
    assert fields["audio_denoiser_model"].default == pre["default_denoiser_model"]
    assert fields["audio_enhancement_model"].default == pre["default_enhancement_model"]
    assert fields["audio_target_loudness_lufs"].default == pre["target_loudness_lufs"]
    assert fields["audio_max_gain_db"].default == pre["max_gain_db"]
    assert fields["asr_language"].default == "fa"
    assert fields["turn_merge_gap_ms"].default == CONSTANTS["merge"]["turn_merge_gap_ms"]
    assert CONSTANTS["merge"]["turn_merge_gap_ms"] == TURN_MERGE_GAP_MS
    for channel, label in CONSTANTS["channel_labels"].items():
        assert render_turns([(int(channel), 0, "سلام")], "inbound", "dual_channel") == (
            f"[{label} 00:00] سلام"
        )


def test_ingest_accepts_only_contract_formats() -> None:
    assert list(audio.ALLOWED_SAMPLE_RATES) == CONSTANTS["accepted_ingest"]["sample_rates_hz"]


@pytest.mark.parametrize("case", _load("gain.json")["cases"], ids=lambda c: str(c["measured_lufs"]))
def test_compute_gain_db_vectors(case: dict[str, Any]) -> None:
    measured = float("nan") if case["measured_lufs"] == "nan" else case["measured_lufs"]
    gain, silent = compute_gain_db(measured, case["target_lufs"], case["max_gain_db"])
    assert (gain, silent) == (case["gain_db"], case["silent"])


@pytest.fixture
def ffmpeg_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str) -> tuple[int, bytes, bytes]:
        calls.append(args)
        return 0, b"", b'{"input_i": "-30.0"}'

    monkeypatch.setattr(audio, "_run", fake_run)
    return calls


def _filter_chains(calls: list[tuple[str, ...]]) -> list[str]:
    return [call[call.index("-af") + 1] for call in calls]


@pytest.mark.parametrize("denoiser", list(CONSTANTS["preprocessing"]["denoise_filters"]))
@pytest.mark.parametrize("enhancement", list(CONSTANTS["preprocessing"]["enhancement_filters"]))
async def test_filter_chain_matches_contract(
    ffmpeg_calls: list[tuple[str, ...]], tmp_path: Path, denoiser: str, enhancement: str
) -> None:
    pre = CONSTANTS["preprocessing"]
    target = tmp_path / "out.wav"
    target.write_bytes(b"\0" * 100)
    config = AudioPreprocessingConfig(
        enabled=True, denoiser_model=denoiser, enhancement_model=enhancement
    )

    report = await audio.preprocess_mono_audio(tmp_path / "in.wav", target, config)

    expected = [CONSTANTS["base_filter"]]
    if pre["denoise_filters"][denoiser]:
        expected.append(pre["denoise_filters"][denoiser])
    expected.extend(pre["enhancement_filters"][enhancement])
    chains = _filter_chains(ffmpeg_calls)
    if enhancement == "speech-telephony-adaptive":
        # Measured -30 LUFS against the -20 target => +10 dB static gain, then the limiter.
        assert chains == [
            ",".join([*expected, pre["adaptive_loudness_probe"]]),
            ",".join([*expected, "volume=10.0dB", pre["adaptive_limiter"]]),
        ]
        assert report is not None and report.gain_db == 10.0 and not report.silent
    else:
        assert chains == [",".join(expected)]
        assert report is None
    output = ffmpeg_calls[-1]
    assert output[output.index("-ar") + 1] == str(CONSTANTS["output_format"]["sample_rate_hz"])
    assert output[output.index("-ac") + 1] == str(CONSTANTS["output_format"]["channels"])
    assert output[output.index("-acodec") + 1] == CONSTANTS["output_format"]["codec"]


async def test_disabled_preprocessing_only_resamples(
    ffmpeg_calls: list[tuple[str, ...]], tmp_path: Path
) -> None:
    target = tmp_path / "out.wav"
    target.write_bytes(b"\0" * 100)
    config = AudioPreprocessingConfig(enabled=False)

    await audio.preprocess_mono_audio(tmp_path / "in.wav", target, config)

    assert _filter_chains(ffmpeg_calls) == [CONSTANTS["base_filter"]]
    assert config.identity == CONSTANTS["preprocessing"]["identity_disabled"]


@pytest.mark.parametrize("case", _load("consolidation.json")["cases"], ids=lambda c: c["name"])
def test_consolidate_segments_vectors(case: dict[str, Any]) -> None:
    rows = [
        (
            item["channel"],
            AsrSegment(
                t_start_ms=item["start_ms"],
                t_end_ms=item["end_ms"],
                text=item["text"],
                confidence=item["confidence"],
                metadata=(
                    {"timestamp_source": item["timestamp_source"]}
                    if item["timestamp_source"]
                    else None
                ),
            ),
        )
        for item in case["input"]
    ]

    result = consolidate_segments(rows, merge_gap_ms=case["merge_gap_ms"])

    assert [
        {
            "channel": channel,
            "start_ms": segment.t_start_ms,
            "end_ms": segment.t_end_ms,
            "text": segment.text,
            "confidence": segment.confidence,
            "timestamp_source": (segment.metadata or {}).get("timestamp_source"),
        }
        for channel, segment in result
    ] == case["expected"]


def _validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Minimal JSON-Schema subset used by segment.schema.json (jsonschema is not a dependency)."""
    errors: list[str] = []
    types = schema.get("type")
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        checks = {
            "object": lambda v: isinstance(v, dict),
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: (
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            ),
            "null": lambda v: v is None,
        }
        if not any(checks[t](value) for t in allowed):
            return [f"{path}: expected {allowed}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append(f"{path}: too short")
    if isinstance(value, (int, float)) and value is not None:
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors.extend(f"{path}: unexpected {key}" for key in value if key not in props)
        for key, sub in props.items():
            if key in value:
                errors.extend(_validate(value[key], sub, f"{path}.{key}"))
    return errors


SEGMENT_SCHEMA = _load("segment.schema.json")
VALID_SEGMENT = {
    "id": 0,
    "channel": 0,
    "start_ms": 0,
    "end_ms": 700,
    "text": "سلام وقت بخیر",
    "confidence": None,
    "speaker": None,
    "timestamp_source": "silero_vad",
    "source": "device",
}


def test_segment_schema_accepts_a_valid_device_and_server_segment() -> None:
    assert _validate(VALID_SEGMENT, SEGMENT_SCHEMA) == []
    server = {**VALID_SEGMENT, "channel": 1, "confidence": 0.8, "timestamp_source": "native"}
    assert _validate({**server, "source": "server"}, SEGMENT_SCHEMA) == []


@pytest.mark.parametrize(
    "patch",
    [
        {"text": ""},
        {"channel": 2},
        {"source": "cloud"},
        {"timestamp_source": "guess"},
        {"confidence": 1.5},
        {"start_ms": -1},
        {"extra": 1},
    ],
)
def test_segment_schema_rejects_invalid_segments(patch: dict[str, Any]) -> None:
    assert _validate({**VALID_SEGMENT, **patch}, SEGMENT_SCHEMA) != []
    # Dropping a required field is also rejected.
    assert _validate({k: v for k, v in VALID_SEGMENT.items() if k != "source"}, SEGMENT_SCHEMA)
