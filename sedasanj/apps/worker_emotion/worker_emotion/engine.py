from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.sentiment import SentimentLabel, valence

TARGET_LABELS: tuple[SentimentLabel, ...] = (
    "angry",
    "sad",
    "neutral",
    "satisfied",
    "happy",
)

RAW_LABEL_MAP: dict[str, dict[str, float]] = {
    "angry": {"angry": 1.0},
    "disgusted": {"angry": 0.6, "sad": 0.4},
    "fearful": {"sad": 1.0},
    "happy": {"happy": 1.0},
    "neutral": {"neutral": 1.0},
    "other": {"neutral": 1.0},
    "sad": {"sad": 1.0},
    "surprised": {"neutral": 1.0},
    "unknown": {"neutral": 1.0},
}


@dataclass(frozen=True, slots=True)
class EmotionPrediction:
    label: SentimentLabel
    score: float
    valence: float
    probabilities: dict[str, float]


def _canonical_label(value: object) -> str | None:
    text = str(value).strip().lower()
    for label in RAW_LABEL_MAP:
        if label in text:
            return label
    return None


def parse_prediction(payload: object) -> EmotionPrediction:
    if not isinstance(payload, dict):
        raise RuntimeError("emotion2vec result is not an object")
    labels = payload.get("labels")
    scores = payload.get("scores")
    if not isinstance(labels, list) or not isinstance(scores, list) or len(labels) != len(scores):
        raise RuntimeError("emotion2vec result is missing aligned labels and scores")

    raw: dict[str, float] = {}
    for label_value, score_value in zip(labels, scores, strict=True):
        label = _canonical_label(label_value)
        try:
            score = float(score_value)
        except (TypeError, ValueError):
            continue
        if label is None or not math.isfinite(score) or score < 0:
            continue
        raw[label] = raw.get(label, 0.0) + score
    raw_total = sum(raw.values())
    if raw_total <= 0:
        raise RuntimeError("emotion2vec result contains no usable scores")

    target: dict[str, float] = dict.fromkeys(TARGET_LABELS, 0.0)
    for raw_label, raw_score in raw.items():
        for target_label, weight in RAW_LABEL_MAP[raw_label].items():
            target[target_label] += (raw_score / raw_total) * weight
    total = sum(target.values())
    probabilities = {label: round(score / total, 6) for label, score in target.items()}
    label = max(TARGET_LABELS, key=lambda item: probabilities[item])
    confidence = probabilities[label]
    weighted_valence = sum(
        valence(target_label, 1.0) * probability
        for target_label, probability in probabilities.items()
    )
    return EmotionPrediction(
        label=label,
        score=round(confidence, 6),
        valence=round(weighted_valence, 6),
        probabilities=probabilities,
    )


class Emotion2VecEngine:
    def __init__(
        self, *, model: str, revision: str, hub: str, device: str, cpu_threads: int
    ) -> None:
        self.model_name = model
        self.model_revision = revision
        self._hub = hub
        self._device = device
        self._cpu_threads = cpu_threads
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()

    async def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_model)
        return self._model

    def _load_model(self) -> Any:
        try:
            import torch
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "voice sentiment dependencies are unavailable; install the emotion extra"
            ) from exc
        torch.set_num_threads(self._cpu_threads)
        return AutoModel(
            model=self.model_name,
            model_revision=self.model_revision,
            hub=self._hub,
            device=self._device,
            disable_update=True,
        )

    async def analyze_many(self, paths: list[Path]) -> list[EmotionPrediction]:
        if not paths:
            return []
        model = await self._ensure_model()
        raw = await asyncio.to_thread(
            model.generate,
            input=[str(path) for path in paths],
            granularity="utterance",
            extract_embedding=False,
            batch_size=1,
        )
        if not isinstance(raw, list) or len(raw) != len(paths):
            raise RuntimeError(
                f"emotion2vec returned {len(raw) if isinstance(raw, list) else 'invalid'} "
                f"results for {len(paths)} windows"
            )
        return [parse_prediction(item) for item in raw]
