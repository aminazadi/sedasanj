from __future__ import annotations

import pytest

from app.errors import ApiError
from app.services.audio import (
    AudioPreprocessingConfig,
    AudioPreprocessingError,
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
