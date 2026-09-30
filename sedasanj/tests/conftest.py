from __future__ import annotations

import io
import struct
import wave
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def wav_factory():
    """Build in-memory PCM WAVs so audio validation can be tested without fixtures on disk."""

    def build(
        *, seconds: float = 1.0, sample_rate: int = 8000, channels: int = 1, tone: int = 440
    ) -> bytes:
        frames = int(seconds * sample_rate)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            payload = bytearray()
            for index in range(frames):
                value = int(8000 * ((index * tone // sample_rate) % 2 * 2 - 1))
                payload += struct.pack("<" + "h" * channels, *([value] * channels))
            handle.writeframes(bytes(payload))
        return buffer.getvalue()

    return build


@pytest.fixture()
def wav_file(tmp_path: Path, wav_factory):
    def build(name: str = "sample.wav", **kwargs) -> Path:
        path = tmp_path / name
        path.write_bytes(wav_factory(**kwargs))
        return path

    return build
