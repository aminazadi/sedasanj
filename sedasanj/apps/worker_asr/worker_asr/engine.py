from __future__ import annotations

import abc
import asyncio
import hashlib
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, normalize_api_key
from app.services.ninerouter import NineRouterClient
from app.services.provider_errors import classify_http, inspect_payload
from app.services.voicesanj import VoiceSanjClient


@dataclass(frozen=True)
class AsrSegment:
    """One recognised span. `t_end_ms == 0` means the engine gave no timestamps."""

    t_start_ms: int
    t_end_ms: int
    text: str
    confidence: float | None = None
    metadata: dict[str, Any] | None = None


class AsrEngine(abc.ABC):
    """§9.1 step 3. Shenava-Koochik internals are still open (§17.1); the interface is not."""

    model_name: str
    model_version: str

    @abc.abstractmethod
    async def transcribe(self, path: Path, *, diarize: bool = False) -> list[AsrSegment]: ...


def _duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate() or 16000
    return int(frames * 1000 / rate)


class ShenavaEngine(AsrEngine):
    """Shenava-Koochik int8 via `tract`, falling back to ONNX Runtime."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.asr_model_name
        self.model_version = settings.asr_model_version
        self._model_path = Path(settings.shenava_model_path)
        self._session: object | None = None

    def _load(self) -> object:
        if self._session is not None:
            return self._session
        if not self._model_path.exists():
            raise RuntimeError(f"ASR model missing at {self._model_path}")
        try:
            import tract  # type: ignore[import-not-found]

            self._session = tract.nnef().model_for_path(str(self._model_path)).into_optimized()
        except ImportError:
            import onnxruntime

            self._session = onnxruntime.InferenceSession(str(self._model_path))
        return self._session

    async def transcribe(self, path: Path, *, diarize: bool = False) -> list[AsrSegment]:
        session = self._load()
        decode = getattr(session, "transcribe", None)
        if decode is None:
            raise RuntimeError(
                "loaded ASR runtime exposes no transcribe entrypoint; "
                "wire the Shenava decoder once the artifact is licensed (§17.1)"
            )
        text = str(decode(str(path)))
        return [AsrSegment(t_start_ms=0, t_end_ms=_duration_ms(path), text=text.strip())]


class WhisperEngine(AsrEngine):
    """OpenAI-compatible speech-to-text for local / remote Whisper endpoints."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.whisper_model
        self.model_version = "openai"
        self._settings = settings

    def _base_url(self) -> str:
        if self._settings.asr_provider_base_url:
            return self._settings.asr_provider_base_url.rstrip("/")
        if self._settings.whisper_base_url:
            return self._settings.whisper_base_url.rstrip("/")
        urls = self._settings.llama_urls
        if not urls:
            raise RuntimeError("WHISPER_BASE_URL or LLAMA_SERVER_URLS is empty")
        return urls[0]

    def _api_key(self) -> str:
        key = normalize_api_key(
            self._settings.asr_provider_api_key or self._settings.openai_api_key
        )
        if not key:
            raise RuntimeError(
                "provider API key is required for whisper ASR; save it in admin model settings"
            )
        return key

    async def transcribe(self, path: Path, *, diarize: bool = False) -> list[AsrSegment]:
        duration = _duration_ms(path)
        # One request per channel. Split only when the file would exceed typical
        # 25 MB cloud STT limits (~10 minutes of 16 kHz mono PCM).
        max_ms = 10 * 60 * 1000
        if duration <= max_ms + 2_000:
            payload = await self._transcribe_file(path)
            return _segments_from_whisper(payload, path)

        rows: list[AsrSegment] = []
        with tempfile.TemporaryDirectory(prefix="cbi-whisper-") as tmp:
            parts = await _split_wav(path, Path(tmp), seconds=max_ms // 1000)
            for index, part in enumerate(parts):
                offset = index * max_ms
                payload = await self._transcribe_file(part)
                for segment in _segments_from_whisper(payload, part):
                    rows.append(
                        AsrSegment(
                            t_start_ms=segment.t_start_ms + offset,
                            t_end_ms=min(segment.t_end_ms + offset, duration),
                            text=segment.text,
                        )
                    )
        if not rows:
            raise RuntimeError("whisper returned empty text")
        return rows

    async def _transcribe_file(self, path: Path) -> object:
        if self._settings.active_ai_provider == "ninerouter_direct":
            client = NineRouterClient(self._settings)
            try:
                return await client.transcribe(
                    path,
                    model=self.model_name,
                    language=self._settings.asr_language,
                    prompt=self._settings.ninerouter_direct_prompt or None,
                )
            finally:
                await client.close()
        audio = path.read_bytes()
        url = f"{self._base_url()}/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._api_key()}"}
        form = {
            "model": self.model_name,
            "language": self._settings.asr_language,
            "response_format": "json",
        }
        if self._settings.ninerouter_asr_prompt:
            form["prompt"] = self._settings.ninerouter_asr_prompt
        timeout = httpx.Timeout(connect=30.0, read=600.0, write=120.0, pool=30.0)
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=timeout, http2=False) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        url,
                        headers=headers,
                        files={"file": (path.name, audio, "audio/wav")},
                        data=form,
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                    await asyncio.sleep(2**attempt)
                    continue
                classified = classify_http(response.status_code, response.text, kind="asr")
                if classified is not None:
                    if classified.retryable is False:
                        raise classified
                    last_error = classified
                    await asyncio.sleep(2**attempt)
                    continue
                try:
                    payload: object = response.json()
                except ValueError as exc:
                    last_error = exc
                    await asyncio.sleep(2**attempt)
                    continue
                inspect_payload(payload, kind="asr")
                return payload
        if last_error is not None:
            raise last_error
        raise RuntimeError("whisper request failed")


async def _split_wav(source: Path, dest_dir: Path, seconds: int) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    pattern = dest_dir / "part_%03d.wav"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-f",
        "segment",
        "-segment_time",
        str(seconds),
        "-reset_timestamps",
        "1",
        "-c",
        "copy",
        str(pattern),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(f"ffmpeg segment failed: {stderr.decode()[:300]}")
    parts = sorted(dest_dir.glob("part_*.wav"))
    if not parts:
        raise RuntimeError("ffmpeg produced no audio chunks")
    return parts


def _segments_from_whisper(payload: object, path: Path) -> list[AsrSegment]:
    duration = _duration_ms(path)
    if not isinstance(payload, dict):
        raise RuntimeError("whisper response is not a JSON object")
    raw_segments = payload.get("segments")
    if isinstance(raw_segments, list) and raw_segments:
        rows: list[AsrSegment] = []
        for index, item in enumerate(raw_segments):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            start_ms = int(float(item.get("start") or 0) * 1000)
            end_raw = item.get("end")
            end_ms = int(float(end_raw) * 1000) if end_raw is not None else duration
            if end_ms <= start_ms:
                next_start_ms = duration
                for candidate in raw_segments[index + 1 :]:
                    if not isinstance(candidate, dict):
                        continue
                    candidate_start_ms = int(float(candidate.get("start") or 0) * 1000)
                    if candidate_start_ms > start_ms:
                        next_start_ms = candidate_start_ms
                        break
                end_ms = max(next_start_ms, start_ms + 1)
            avg_logprob = item.get("avg_logprob")
            confidence = None
            if isinstance(avg_logprob, (int, float)):
                confidence = max(0.0, min(1.0, 2.718281828 ** float(avg_logprob)))
            rows.append(
                AsrSegment(
                    t_start_ms=start_ms,
                    t_end_ms=end_ms,
                    text=text,
                    confidence=confidence,
                    metadata={
                        key: item.get(key)
                        for key in (
                            "avg_logprob",
                            "no_speech_prob",
                            "compression_ratio",
                            "timestamp_source",
                            "speaker",
                        )
                        if item.get(key) is not None
                    },
                )
            )
        if rows:
            return rows
    text = str(payload.get("text") or "").strip()
    if not text:
        raise RuntimeError("whisper returned empty text")
    return [AsrSegment(t_start_ms=0, t_end_ms=duration, text=text)]


class VoiceSanjEngine(AsrEngine):
    """Remote Persian ASR via aiservice.voicesanj.ir (async task + poll)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.model_name = settings.voicesanj_asr_model
        self._models = (
            settings.correction_audio_models
            if settings.correction_enabled
            and settings.correction_mode in {"audio_only", "two_stage"}
            else [settings.voicesanj_asr_model]
        )
        self.model_version = "voicesanj"
        self._prompt = settings.ninerouter_asr_prompt or None
        self._client = VoiceSanjClient(
            settings.model_copy(
                update={
                    "voicesanj_base_url": (
                        settings.asr_provider_base_url or settings.voicesanj_base_url
                    ),
                    "voicesanj_api_key": (
                        settings.asr_provider_api_key or settings.voicesanj_api_key
                    ),
                }
            )
        )

    async def transcribe(self, path: Path, *, diarize: bool = False) -> list[AsrSegment]:
        return await self._transcribe_file(path, diarize=diarize)

    async def _transcribe_file(self, path: Path, *, diarize: bool = False) -> list[AsrSegment]:
        payload = await self._client.transcribe(
            path,
            model=self.model_name,
            models=self._models if len(self._models) > 1 else None,
            response_format="verbose_json",
            beam_size=5,
            vad_filter=True,
            prompt=self._prompt,
            ensure_timestamps=True,
            diarize=diarize and self._settings.mono_diarization_enabled,
            turn_min_seconds=self._settings.turn_min_seconds,
            turn_padding_seconds=self._settings.turn_padding_seconds,
        )
        if payload.get("model"):
            self.model_name = str(payload["model"])
        return _segments_from_whisper(payload, path)


class FixtureEngine(AsrEngine):
    """Deterministic stand-in used until the Shenava artifact lands (§17)."""

    def __init__(self) -> None:
        self.model_name = "fixture"
        self.model_version = "v1"

    async def transcribe(self, path: Path, *, diarize: bool = False) -> list[AsrSegment]:
        duration = _duration_ms(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
        return [
            AsrSegment(
                t_start_ms=0,
                t_end_ms=duration,
                text=f"متن آزمایشی برای فایل {path.stem} ({digest}).",
            )
        ]


def build_engine(settings: Settings) -> AsrEngine:
    if settings.asr_engine == "fixture":
        return FixtureEngine()
    if settings.asr_engine == "whisper":
        return WhisperEngine(settings)
    if settings.asr_engine == "voicesanj":
        return VoiceSanjEngine(settings)
    return ShenavaEngine(settings)
