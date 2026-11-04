"""Silero-VAD segmented decoding: a Python port of Jalase-Negar's live pipeline.

Reference: jalase-negar/lib/core/asr/{live_pipeline,asr_common}.dart. The phone
cuts speech with Silero VAD, gives every span 0.75 s of context on each side,
lifts quiet audio, decodes each span once and drops overlapping repeats. This
module runs the same steps over a whole file so call recordings get the same
pipeline. The shared contract pins the default parameters.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

CONTRACT = json.loads(Path(__file__).with_name("vad_segment_contract.json").read_text())
SAMPLE_RATE = CONTRACT["sample_rate"]
TARGET_SPEECH_RMS = CONTRACT["target_rms"]
MAX_QUIET_GAIN = CONTRACT["max_gain"]
PRE_ROLL_SAMPLES = CONTRACT["pre_roll_samples"]
POST_ROLL_SAMPLES = CONTRACT["post_roll_samples"]
DUPLICATE_WINDOW_MS = CONTRACT["duplicate_window_ms"]
RECENT_KEEP = CONTRACT["recent_keep"]
SEGMENTER_NAME = "silero_vad"
VAD_THRESHOLD = CONTRACT["threshold"]
VAD_MIN_SILENCE_SECONDS = CONTRACT["min_silence_seconds"]
VAD_MIN_SPEECH_SECONDS = CONTRACT["min_speech_seconds"]
VAD_MAX_SPEECH_SECONDS = CONTRACT["max_speech_seconds"]
VAD_WINDOW_SIZE = CONTRACT["window_size"]

_ARABIC_MARKS = re.compile("[ً-ٰٟ]")


class NoVadSpeechError(RuntimeError):
    """The VAD found no speech span, or every span decoded to empty text."""


@dataclass(frozen=True)
class VadSpan:
    start_sample: int
    samples: np.ndarray


def normalize_persian_asr_text(text: str) -> str:
    """Same cleanup as the app's normalizePersianAsrText (asr_common.dart)."""
    out = (
        text.replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .replace("ۀ", "هٔ")
        .replace("ـ", "")
    )
    out = _ARABIC_MARKS.sub("", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r" *\n *", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def normalize_quiet_audio(samples: np.ndarray) -> np.ndarray:
    """Remove DC offset and lift quiet speech (asr_common.dart normalizeQuietAudio)."""
    if samples.size == 0:
        return samples
    mean = float(samples.mean(dtype=np.float64))
    centered = samples.astype(np.float64) - mean
    peak = float(np.abs(centered).max())
    rms = math.sqrt(float(np.mean(np.square(centered))))
    if rms < 0.001 or peak == 0:
        return samples
    gain = min(MAX_QUIET_GAIN, TARGET_SPEECH_RMS / rms)
    if gain <= 1.05:
        return samples
    return np.clip(centered * gain, -1.0, 1.0).astype(np.float32)


def add_asr_context(audio: np.ndarray, start: int, end: int) -> np.ndarray:
    """Return [start - pre_roll, end + post_roll) padded with silence at file edges."""
    wanted_start = start - PRE_ROLL_SAMPLES
    left = max(0, wanted_start)
    right = min(len(audio), end + POST_ROLL_SAMPLES)
    missing = max(0, PRE_ROLL_SAMPLES - (start - left))
    body = audio[left:right]
    if missing:
        return np.concatenate([np.zeros(missing, dtype=np.float32), body])
    return body


def is_duplicate_transcript(
    candidate: str, start_ms: int, end_ms: int, emitted: list[tuple[int, int, str]]
) -> bool:
    tokens = {t for t in candidate.split(" ") if t}
    for prev_start, prev_end, previous in emitted:
        if not (
            prev_start < end_ms + DUPLICATE_WINDOW_MS and prev_end > start_ms - DUPLICATE_WINDOW_MS
        ):
            continue
        if previous == candidate:
            return True
        if len(candidate) >= CONTRACT["duplicate_min_chars"] and (
            candidate in previous or previous in candidate
        ):
            return True
        previous_tokens = {t for t in previous.split(" ") if t}
        if len(tokens) < 3 or len(previous_tokens) < 3:
            continue
        shared = len(tokens & previous_tokens)
        if shared / min(len(tokens), len(previous_tokens)) >= CONTRACT["duplicate_token_ratio"]:
            return True
    return False


class SileroVad:
    """Silero VAD through sherpa-onnx with the app's parameters."""

    def __init__(self, model_path: str, *, threshold: float = VAD_THRESHOLD):
        self.model_path = model_path
        self.threshold = threshold

    def spans(self, blocks: Iterable[np.ndarray]) -> Iterable[VadSpan]:
        import sherpa_onnx

        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = self.model_path
        config.silero_vad.threshold = self.threshold
        config.silero_vad.min_silence_duration = VAD_MIN_SILENCE_SECONDS
        config.silero_vad.min_speech_duration = VAD_MIN_SPEECH_SECONDS
        config.silero_vad.max_speech_duration = VAD_MAX_SPEECH_SECONDS
        config.silero_vad.window_size = VAD_WINDOW_SIZE
        config.sample_rate = SAMPLE_RATE
        config.num_threads = 1
        vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)
        for block in blocks:
            vad.accept_waveform(block)
            while not vad.empty():
                seg = vad.front
                yield VadSpan(int(seg.start), np.asarray(seg.samples, dtype=np.float32))
                vad.pop()
        vad.flush()
        while not vad.empty():
            seg = vad.front
            yield VadSpan(int(seg.start), np.asarray(seg.samples, dtype=np.float32))
            vad.pop()


def decode_file(
    path: Path,
    vad: SileroVad,
    decode: Callable[[np.ndarray], str],
    on_event: Callable[[str], None],
) -> tuple[list[dict], float]:
    """Stream PCM blocks and read context by offset from the same on-disk timeline."""
    with tempfile.TemporaryDirectory(prefix="asr-silero-", dir=path.parent) as scratch:
        try:
            info = sf.info(path)
        except sf.LibsndfileError:
            info = None
        if info is None or info.samplerate != SAMPLE_RATE or info.channels != 1:
            normalized = Path(scratch) / "mono.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-ac",
                    "1",
                    "-ar",
                    str(SAMPLE_RATE),
                    "-c:a",
                    "pcm_f32le",
                    str(normalized),
                ],
                check=True,
                capture_output=True,
            )
            path = normalized
        with sf.SoundFile(path) as audio, sf.SoundFile(path) as context:

            def prepare(span: VadSpan) -> np.ndarray:
                offset = max(0, span.start_sample - PRE_ROLL_SAMPLES)
                context.seek(offset)
                clip = context.read(
                    PRE_ROLL_SAMPLES
                    + len(span.samples)
                    + POST_ROLL_SAMPLES
                    - max(0, PRE_ROLL_SAMPLES - span.start_sample),
                    dtype="float32",
                )
                start = span.start_sample - offset
                return add_asr_context(clip, start, start + len(span.samples))

            def blocks() -> Iterable[np.ndarray]:
                offset = 0
                next_report = 60 * SAMPLE_RATE
                for block in audio.blocks(blocksize=VAD_WINDOW_SIZE, dtype="float32"):
                    offset += len(block)
                    if offset >= next_report:
                        on_event(
                            f"Processed {offset // SAMPLE_RATE}/{len(audio) // SAMPLE_RATE} "
                            "audio seconds"
                        )
                        next_report += 60 * SAMPLE_RATE
                    yield block

            return decode_spans(
                vad.spans(blocks()), prepare, decode, on_event, total_samples=len(audio)
            ), len(audio) / SAMPLE_RATE


def decode_spans(
    spans: Iterable[VadSpan],
    prepare: Callable[[VadSpan], np.ndarray],
    decode: Callable[[np.ndarray], str],
    on_event: Callable[[str], None] | None = None,
    *,
    total_samples: int,
) -> list[dict]:
    """Decode one utterance at a time and retain only text and timestamps."""
    event = on_event or (lambda _m: None)
    recent: list[tuple[int, int, str]] = []
    segments: list[dict] = []
    for span in spans:
        start = span.start_sample
        end = min(start + len(span.samples), total_samples)
        if end <= start:
            continue
        start_ms = start * 1000 // SAMPLE_RATE
        end_ms = end * 1000 // SAMPLE_RATE
        prepared = normalize_quiet_audio(prepare(span))
        text = normalize_persian_asr_text(decode(prepared))
        if not text:
            continue
        key = re.sub(r"\s+", " ", text).strip().lower()
        if is_duplicate_transcript(key, start_ms, end_ms, recent):
            continue
        recent.append((start_ms, end_ms, key))
        if len(recent) > RECENT_KEEP:
            recent.pop(0)
        segments.append(
            {
                "id": len(segments),
                "start": start_ms / 1000.0,
                "end": end_ms / 1000.0,
                "text": text,
                "timestamp_source": SEGMENTER_NAME,
            }
        )
    event(f"Decoded {len(segments)} VAD segment(s)")
    if not segments:
        raise NoVadSpeechError("Silero VAD segmentation produced no text")
    return segments
