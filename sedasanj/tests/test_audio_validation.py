from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from app.errors import ApiError
from app.services.audio import (
    ADAPTIVE_ENHANCEMENT_MODEL,
    AudioPreprocessingConfig,
    AudioPreprocessingError,
    _measure_loudness,
    compute_gain_db,
    parse_integrated_loudness,
    preprocess_mono_audio,
    probe_wav_bytes,
    probe_wav_file,
)


async def test_probe_accepts_8khz_mono(wav_factory) -> None:
    probe = await probe_wav_bytes(wav_factory(seconds=1.0, sample_rate=8000, channels=1))
    assert (probe.sample_rate, probe.channels, probe.codec) == (8000, 1, "pcm_s16le")
    assert 950 <= probe.duration_ms <= 1050
    assert len(probe.sha256) == 64


async def test_probe_accepts_16khz_stereo(wav_factory) -> None:
    probe = await probe_wav_bytes(wav_factory(seconds=0.5, sample_rate=16000, channels=2))
    assert (probe.sample_rate, probe.channels) == (16000, 2)


@pytest.mark.parametrize(
    ("denoiser", "enhancement"),
    [
        ("none", "none"),
        ("speech-afftdn-balanced", "speech-clarity-balanced"),
        ("speech-afftdn-strong", "speech-clarity-strong"),
    ],
)
async def test_preprocessing_produces_provider_ready_pcm_wav(
    wav_file, tmp_path, denoiser: str, enhancement: str
) -> None:
    source = wav_file(sample_rate=8000, channels=1)
    target = tmp_path / f"processed-{denoiser}-{enhancement}.wav"
    await preprocess_mono_audio(
        source,
        target,
        AudioPreprocessingConfig(
            enabled=True,
            denoiser_model=denoiser,
            enhancement_model=enhancement,
        ),
    )
    probe = await probe_wav_file(target)
    assert (probe.sample_rate, probe.channels, probe.codec) == (16000, 1, "pcm_s16le")
    assert 950 <= probe.duration_ms <= 1050


async def test_preprocessing_rejects_unknown_model(wav_file, tmp_path) -> None:
    with pytest.raises(AudioPreprocessingError, match="unsupported denoiser"):
        await preprocess_mono_audio(
            wav_file(),
            tmp_path / "bad.wav",
            AudioPreprocessingConfig(enabled=True, denoiser_model="unknown"),
        )


async def test_probe_rejects_unsupported_sample_rate(wav_factory) -> None:
    with pytest.raises(ApiError) as excinfo:
        await probe_wav_bytes(wav_factory(sample_rate=44100))
    assert excinfo.value.code == "unsupported_audio"


async def test_probe_rejects_non_wav_payload() -> None:
    with pytest.raises(ApiError) as excinfo:
        await probe_wav_bytes(b"this is not audio at all")
    assert excinfo.value.code == "unsupported_audio"


def _sine_wav(path: Path, *, amplitude: int, seconds: float = 4.0, rate: int = 8000) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 300 * i / rate)))
                for i in range(int(seconds * rate))
            )
        )
    return path


@pytest.mark.parametrize(
    ("measured", "expected"),
    [
        (-45.0, (25.0, False)),  # a faint caller leg is lifted to the target
        (-52.0, (30.0, False)),  # the lift is capped by max_gain_db
        (-20.2, (0.0, False)),  # inaudible difference: no extra filter
        (-14.0, (-6.0, False)),  # a hot leg is trimmed, never by more than the attenuation cap
        (-60.0, (0.0, True)),  # no usable speech: never amplify line noise
        (None, (0.0, True)),
        (float("-inf"), (0.0, True)),
    ],
)
def test_compute_gain_matches_channel_to_target(
    measured: float | None, expected: tuple[float, bool]
) -> None:
    assert compute_gain_db(measured, -20.0, 30.0) == expected


def test_compute_gain_honours_a_lower_gain_cap() -> None:
    assert compute_gain_db(-45.0, -20.0, 10.0) == (10.0, False)


def test_parse_integrated_loudness() -> None:
    log = b'[Parsed_loudnorm_0 @ 0x1] \n{\n\t"input_i" : "-31.42",\n\t"input_tp" : "-20.1"\n}\n'
    assert parse_integrated_loudness(log) == -31.42
    assert parse_integrated_loudness(b'{ "input_i" : "-inf" }') is None
    with pytest.raises(AudioPreprocessingError, match="printed no result"):
        parse_integrated_loudness(b"no json here")
    with pytest.raises(AudioPreprocessingError, match="unreadable"):
        parse_integrated_loudness(b'{ "input_tp" : "-1.0" }')


def test_adaptive_config_validates_ranges_and_identity() -> None:
    base = AudioPreprocessingConfig(enabled=True, enhancement_model=ADAPTIVE_ENHANCEMENT_MODEL)
    base.validate()
    assert base.adaptive
    assert base.identity.endswith("@-20LUFS/30dB")
    with pytest.raises(AudioPreprocessingError, match="target loudness"):
        AudioPreprocessingConfig(
            enabled=True, enhancement_model=ADAPTIVE_ENHANCEMENT_MODEL, target_loudness_lufs=-5
        ).validate()
    with pytest.raises(AudioPreprocessingError, match="maximum gain"):
        AudioPreprocessingConfig(
            enabled=True, enhancement_model=ADAPTIVE_ENHANCEMENT_MODEL, max_gain_db=60
        ).validate()
    # The numbers only matter to the adaptive model.
    assert "LUFS" not in AudioPreprocessingConfig(enabled=True).identity
    assert not AudioPreprocessingConfig(enhancement_model=ADAPTIVE_ENHANCEMENT_MODEL).adaptive


async def test_adaptive_model_lifts_a_faint_channel_to_the_target(tmp_path) -> None:
    config = AudioPreprocessingConfig(
        enabled=True, denoiser_model="none", enhancement_model=ADAPTIVE_ENHANCEMENT_MODEL
    )
    faint = _sine_wav(tmp_path / "faint.wav", amplitude=200)
    loud = _sine_wav(tmp_path / "loud.wav", amplitude=9000)
    faint_out, loud_out = tmp_path / "faint-out.wav", tmp_path / "loud-out.wav"

    faint_report = await preprocess_mono_audio(faint, faint_out, config)
    loud_report = await preprocess_mono_audio(loud, loud_out, config)

    assert faint_report is not None and loud_report is not None
    assert not faint_report.silent and faint_report.gain_db > 15
    assert not loud_report.silent and loud_report.gain_db < 0
    faint_lufs = await _measure_loudness(faint_out, [])
    loud_lufs = await _measure_loudness(loud_out, [])
    assert faint_lufs is not None and loud_lufs is not None
    assert abs(faint_lufs - (-20.0)) < 3
    assert abs(faint_lufs - loud_lufs) < 3  # both sides end up at the same level
    probe = await probe_wav_file(faint_out)
    assert (probe.sample_rate, probe.channels, probe.codec) == (16000, 1, "pcm_s16le")


async def test_adaptive_model_does_not_amplify_a_silent_channel(tmp_path) -> None:
    config = AudioPreprocessingConfig(
        enabled=True, denoiser_model="none", enhancement_model=ADAPTIVE_ENHANCEMENT_MODEL
    )
    noise_floor = _sine_wav(tmp_path / "floor.wav", amplitude=5)
    report = await preprocess_mono_audio(noise_floor, tmp_path / "floor-out.wav", config)
    assert report is not None and report.silent and report.gain_db == 0.0


async def test_other_models_report_nothing(wav_file, tmp_path) -> None:
    report = await preprocess_mono_audio(
        wav_file(), tmp_path / "plain.wav", AudioPreprocessingConfig(enabled=True)
    )
    assert report is None
