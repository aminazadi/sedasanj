from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from asr_service.infrastructure.storage import MODEL_DIR


@dataclass(frozen=True)
class SpeechRegion:
    start: float
    end: float
    speaker: int | None = None


def _merge_regions(
    regions: list[SpeechRegion], *, min_seconds: float, padding_seconds: float, duration: float
) -> list[SpeechRegion]:
    padded = [
        SpeechRegion(
            max(0.0, item.start - padding_seconds),
            min(duration, item.end + padding_seconds),
            item.speaker,
        )
        for item in regions
        if item.end - item.start >= min_seconds
    ]
    merged: list[SpeechRegion] = []
    for item in sorted(padded, key=lambda row: (row.start, row.speaker or 0)):
        if (
            merged
            and merged[-1].speaker == item.speaker
            and item.start <= merged[-1].end + 0.35
        ):
            previous = merged[-1]
            merged[-1] = SpeechRegion(previous.start, max(previous.end, item.end), item.speaker)
        else:
            merged.append(item)
    return merged


def vad_regions(
    path: str | Path, *, min_seconds: float = 0.3, padding_seconds: float = 0.2
) -> list[SpeechRegion]:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    duration = len(mono) / max(sample_rate, 1)
    frame_samples = max(1, int(sample_rate * 0.03))
    frames = [mono[index : index + frame_samples] for index in range(0, len(mono), frame_samples)]
    energy = np.asarray(
        [float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0 for frame in frames]
    )
    if not len(energy) or float(energy.max(initial=0.0)) <= 1e-6:
        return []
    noise = float(np.percentile(energy, 20))
    threshold = max(noise * 3.0, float(energy.max()) * 0.08, 1e-5)
    active = energy >= threshold
    bridge = max(1, int(0.35 / 0.03))
    last_active = -bridge - 1
    start: int | None = None
    raw: list[SpeechRegion] = []
    for index, is_active in enumerate(active):
        if is_active:
            if start is None and index - last_active > bridge:
                start = index
            last_active = index
        if start is not None and index - last_active > bridge:
            raw.append(SpeechRegion(start * 0.03, min(duration, (last_active + 1) * 0.03)))
            start = None
    if start is not None:
        raw.append(SpeechRegion(start * 0.03, min(duration, (last_active + 1) * 0.03)))
    return _merge_regions(
        raw, min_seconds=min_seconds, padding_seconds=padding_seconds, duration=duration
    )


def diarization_regions(
    path: str | Path,
    *,
    min_seconds: float = 0.3,
    padding_seconds: float = 0.2,
) -> list[SpeechRegion]:
    root = MODEL_DIR / "sherpa-diarization-2speaker"
    segmentation = root / "model.onnx"
    embedding = root / "speaker-embedding.onnx"
    if not (root / ".complete").is_file() or not segmentation.is_file() or not embedding.is_file():
        raise RuntimeError("Install sherpa-diarization-2speaker before diarizing mono audio")
    import sherpa_onnx

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(segmentation), window_shift_ratio=0.1
            )
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding)),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=2),
        min_duration_on=min_seconds,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError("Invalid local speaker diarization model bundle")
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio[:, 0]
    if sample_rate != diarizer.sample_rate:
        target_length = max(1, round(len(mono) * diarizer.sample_rate / sample_rate))
        mono = np.interp(
            np.linspace(0.0, 1.0, target_length, endpoint=False),
            np.linspace(0.0, 1.0, len(mono), endpoint=False),
            mono,
        ).astype(np.float32)
        sample_rate = diarizer.sample_rate
    result = diarizer.process(mono).sort_by_start_time()
    duration = len(mono) / max(sample_rate, 1)
    return _merge_regions(
        [SpeechRegion(float(item.start), float(item.end), int(item.speaker)) for item in result],
        min_seconds=min_seconds,
        padding_seconds=padding_seconds,
        duration=duration,
    )


def _valid_native_segments(result: dict, duration: float) -> bool:
    rows = result.get("segments")
    if not isinstance(rows, list) or not rows:
        return False
    valid = [row for row in rows if isinstance(row, dict) and str(row.get("text") or "").strip()]
    if not valid:
        return False
    parsed: list[tuple[float, float]] = []
    try:
        parsed = [
            (float(row.get("start") or 0), float(row.get("end") or 0)) for row in valid
        ]
    except (TypeError, ValueError):
        return False
    if len(parsed) == 1 and duration >= 8:
        start, end = parsed[0]
        if start <= 0.05 and end >= duration - 0.05:
            return False
    previous_start = -1.0
    for start, end in parsed:
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end <= start
            or end > duration + 0.5
            or start < previous_start
        ):
            return False
        previous_start = start
    return True


def _speaker_for(start: float, end: float, regions: list[SpeechRegion]) -> int | None:
    overlaps = [
        (max(0.0, min(end, region.end) - max(start, region.start)), region.speaker)
        for region in regions
    ]
    overlap, speaker = max(overlaps, default=(0.0, None), key=lambda item: item[0])
    return speaker if overlap > 0 else None


def normalize_transcription(
    path: str | Path,
    result: dict,
    decode: Callable[[Path], dict],
    *,
    ensure_timestamps: bool,
    diarize: bool,
    min_seconds: float,
    padding_seconds: float,
) -> dict:
    if not ensure_timestamps:
        return result
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    duration = len(audio) / max(sample_rate, 1)
    speaker_regions = (
        diarization_regions(path, min_seconds=min_seconds, padding_seconds=padding_seconds)
        if diarize
        else []
    )
    if _valid_native_segments(result, duration):
        result["segments"] = [
            {
                **row,
                "timestamp_source": "native",
                **(
                    {"speaker": _speaker_for(float(row.get("start") or 0), float(row["end"]), speaker_regions)}
                    if diarize
                    else {}
                ),
            }
            for row in result["segments"]
            if isinstance(row, dict) and str(row.get("text") or "").strip()
        ]
        return result
    regions = speaker_regions or vad_regions(
        path, min_seconds=min_seconds, padding_seconds=padding_seconds
    )
    if not regions:
        raise RuntimeError("No speech regions were detected for timestamp recovery")
    recovered: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="asr-regions-") as temp_dir:
        for index, region in enumerate(regions):
            start_sample = max(0, int(region.start * sample_rate))
            end_sample = min(len(audio), int(region.end * sample_rate))
            if end_sample <= start_sample:
                continue
            part = Path(temp_dir) / f"region-{index:04d}.wav"
            sf.write(part, audio[start_sample:end_sample], sample_rate, subtype="PCM_16")
            partial = decode(part)
            text = str(partial.get("text") or "").strip()
            if not text:
                continue
            partial_duration = region.end - region.start
            if _valid_native_segments(partial, partial_duration):
                for row in partial["segments"]:
                    recovered.append(
                        {
                            **row,
                            "start": region.start + float(row.get("start") or 0),
                            "end": min(region.end, region.start + float(row.get("end") or 0)),
                            "timestamp_source": "diarization" if diarize else "vad_window",
                            **({"speaker": region.speaker} if region.speaker is not None else {}),
                        }
                    )
            else:
                recovered.append(
                    {
                        "id": len(recovered),
                        "start": region.start,
                        "end": region.end,
                        "text": text,
                        "timestamp_source": "diarization" if diarize else "vad_window",
                        **({"speaker": region.speaker} if region.speaker is not None else {}),
                    }
                )
    if not recovered:
        raise RuntimeError("ASR returned no text for detected speech regions")
    result["segments"] = recovered
    result["text"] = " ".join(str(row["text"]).strip() for row in recovered)
    result["duration"] = result.get("duration") or duration
    result["duration_after_vad"] = sum(region.end - region.start for region in regions)
    return result
