from __future__ import annotations

import asyncio
import hashlib
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.errors import ApiError

ALLOWED_SAMPLE_RATES = (8000, 16000)
ALLOWED_CODECS = ("pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s32le", "pcm_f32le")

DENOISER_MODELS: dict[str, tuple[str, str]] = {
    "none": ("بدون حذف نویز", "فقط تبدیل استاندارد صوت انجام می‌شود."),
    "speech-afftdn-balanced": (
        "حذف نویز گفتار — متعادل",
        "کاهش نویز تطبیقی مناسب مکالمه، با حفظ طبیعی بودن صدا.",
    ),
    "speech-afftdn-strong": (
        "حذف نویز گفتار — قوی",
        "کاهش شدیدتر نویز برای خطوط تلفنی پرنویز؛ ممکن است بخشی از جزئیات ضعیف را کم کند.",
    ),
}

ENHANCEMENT_MODELS: dict[str, tuple[str, str]] = {
    "none": ("بدون بهبود کیفیت", "سطح و طیف صدا دست‌نخورده می‌ماند."),
    "speech-clarity-balanced": (
        "وضوح گفتار — متعادل",
        "حذف فرکانس‌های خارج از باند گفتار و یکنواخت‌سازی کنترل‌شده سطح صدا.",
    ),
    "speech-clarity-strong": (
        "وضوح گفتار — قوی",
        "فشرده‌سازی دامنه و تقویت وضوح برای صدای بسیار کم یا ناهمگون.",
    ),
}


class AudioPreprocessingError(RuntimeError):
    """A deterministic local audio-preparation failure."""


@dataclass(frozen=True)
class AudioPreprocessingConfig:
    enabled: bool = False
    denoiser_model: str = "speech-afftdn-balanced"
    enhancement_model: str = "speech-clarity-balanced"

    def validate(self) -> None:
        if self.denoiser_model not in DENOISER_MODELS:
            raise AudioPreprocessingError(
                f"unsupported denoiser model: {self.denoiser_model}"
            )
        if self.enhancement_model not in ENHANCEMENT_MODELS:
            raise AudioPreprocessingError(
                f"unsupported enhancement model: {self.enhancement_model}"
            )

    @property
    def identity(self) -> str:
        if not self.enabled:
            return "preprocess:none"
        return f"denoise:{self.denoiser_model}+enhance:{self.enhancement_model}"


@dataclass(frozen=True)
class AudioProbe:
    sample_rate: int
    channels: int
    duration_ms: int
    bytes: int
    sha256: str
    codec: str


async def _run(*args: str) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return process.returncode or 0, stdout, stderr


async def probe_wav_bytes(data: bytes) -> AudioProbe:
    """Validate the upload with ffprobe before it reaches MinIO (§4.3)."""
    with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
        handle.write(data)
        handle.flush()
        return await probe_wav_file(Path(handle.name), payload=data)


async def probe_wav_file(path: Path, payload: bytes | None = None) -> AudioProbe:
    code, stdout, stderr = await _run(
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    )
    if code != 0:
        raise ApiError("unsupported_audio", f"ffprobe rejected the file: {stderr.decode()[:200]}")

    info = json.loads(stdout or b"{}")
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if len(streams) != 1:
        raise ApiError("unsupported_audio", "exactly one audio stream is required")
    stream = streams[0]
    container = (info.get("format", {}).get("format_name") or "").split(",")
    if "wav" not in container:
        raise ApiError("unsupported_audio", f"container must be wav, got {container}")

    codec = str(stream.get("codec_name"))
    if codec not in ALLOWED_CODECS:
        raise ApiError("unsupported_audio", f"linear PCM required, got {codec}")

    channels = int(stream.get("channels", 0))
    if channels not in (1, 2):
        raise ApiError("unsupported_audio", f"1 or 2 channels required, got {channels}")

    sample_rate = int(stream.get("sample_rate", 0))
    if sample_rate not in ALLOWED_SAMPLE_RATES:
        raise ApiError("unsupported_audio", f"8 kHz or 16 kHz required, got {sample_rate}")

    duration_seconds = float(
        stream.get("duration") or info.get("format", {}).get("duration") or 0.0
    )
    if duration_seconds <= 0:
        raise ApiError("unsupported_audio", "audio has no measurable duration")

    if payload is None:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        sha256 = digest.hexdigest()
    else:
        size = len(payload)
        sha256 = hashlib.sha256(payload).hexdigest()
    return AudioProbe(
        sample_rate=sample_rate,
        channels=channels,
        duration_ms=int(math.ceil(duration_seconds * 1000)),
        bytes=size,
        sha256=sha256,
        codec=codec,
    )


async def resample_to_16k(source: Path, target: Path) -> None:
    code, _, stderr = await _run(
        "ffmpeg", "-y", "-i", str(source), "-ar", "16000", "-acodec", "pcm_s16le", str(target)
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg resample failed: {stderr.decode()[:300]}")


async def preprocess_mono_audio(
    source: Path, target: Path, config: AudioPreprocessingConfig
) -> None:
    """Prepare one mono speech channel for ASR using an explicit local pipeline.

    The output is always mono, 16 kHz, signed 16-bit PCM WAV.  When the feature
    is enabled, the selected denoiser runs before the selected clarity model.
    A failure is terminal for this attempt: silently sending the raw file would
    make the admin setting misleading and produce irreproducible transcripts.
    """
    config.validate()
    filters = ["aresample=16000"]
    if config.enabled:
        if config.denoiser_model == "speech-afftdn-balanced":
            filters.append("afftdn=nr=12:nf=-50:tn=1")
        elif config.denoiser_model == "speech-afftdn-strong":
            filters.append("afftdn=nr=20:nf=-45:tn=1")

        if config.enhancement_model == "speech-clarity-balanced":
            filters.extend(
                ["highpass=f=80", "lowpass=f=7600", "dynaudnorm=f=150:g=9:p=0.95"]
            )
        elif config.enhancement_model == "speech-clarity-strong":
            filters.extend(
                [
                    "highpass=f=100",
                    "lowpass=f=7200",
                    "acompressor=threshold=0.125:ratio=3:attack=10:release=120:makeup=2",
                    "dynaudnorm=f=120:g=7:p=0.92",
                ]
            )

    code, _, stderr = await _run(
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-af",
        ",".join(filters),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-acodec",
        "pcm_s16le",
        str(target),
    )
    if code != 0:
        detail = " ".join(stderr.decode(errors="replace").split())[-500:]
        raise AudioPreprocessingError(f"ffmpeg audio preprocessing failed: {detail}")
    if not target.is_file() or target.stat().st_size <= 44:
        raise AudioPreprocessingError("audio preprocessing produced an empty WAV file")


async def split_channels(source: Path, left: Path, right: Path) -> None:
    code, _, stderr = await _run(
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        "[0:a]channelsplit=channel_layout=stereo[l][r]",
        "-map",
        "[l]",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(left),
        "-map",
        "[r]",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(right),
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg channel split failed: {stderr.decode()[:300]}")


async def merge_to_stereo(left: Path, right: Path, target: Path) -> None:
    """Merge two mono legs (caller, callee) into one stereo file: L=caller, R=callee."""
    code, _, stderr = await _run(
        "ffmpeg",
        "-y",
        "-i",
        str(left),
        "-i",
        str(right),
        "-filter_complex",
        "[0:a][1:a]amerge=inputs=2[a]",
        "-map",
        "[a]",
        "-acodec",
        "pcm_s16le",
        str(target),
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg merge failed: {stderr.decode()[:300]}")
