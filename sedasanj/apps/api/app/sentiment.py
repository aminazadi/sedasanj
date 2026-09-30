"""Text and voice sentiment math shared by extraction and the API."""

from __future__ import annotations

from typing import Any, Literal, cast

SentimentLabel = Literal["angry", "sad", "neutral", "satisfied", "happy"]
SentimentTrajectory = Literal["improved", "worsened", "stable"]
SentimentSource = Literal["text", "voice", "fused"]

SENTIMENT_LABELS: tuple[str, ...] = ("angry", "sad", "neutral", "satisfied", "happy")
SENTIMENT_SET: frozenset[str] = frozenset(SENTIMENT_LABELS)
TRAJECTORY_THRESHOLD = 0.12
TRAJECTORIES: frozenset[str] = frozenset({"improved", "worsened", "stable"})

# Base valence on [0, 1]: angry < sad < neutral < satisfied < happy.
_BASE_VALENCE: dict[str, float] = {
    "angry": 0.0,
    "sad": 0.25,
    "negative": 0.0,
    "neutral": 0.5,
    "satisfied": 0.75,
    "happy": 1.0,
    "positive": 1.0,
}

_SENTIMENT_ALIASES = {
    "angry": "angry",
    "sad": "sad",
    "neutral": "neutral",
    "satisfied": "satisfied",
    "happy": "happy",
    "positive": "happy",
    "negative": "sad",
    "عصبانی": "angry",
    "خشمگین": "angry",
    "ناراحت": "sad",
    "غمگین": "sad",
    "خنثی": "neutral",
    "بی‌طرف": "neutral",
    "بي طرف": "neutral",
    "راضی": "satisfied",
    "خشنود": "satisfied",
    "خوشحال": "happy",
    "مثبت": "happy",
    "منفی": "sad",
}


def normalize_sentiment(value: object) -> object:
    if not isinstance(value, str):
        return value
    mapped = _SENTIMENT_ALIASES.get(value.strip()) or _SENTIMENT_ALIASES.get(value.strip().lower())
    if mapped is None:
        raise ValueError("sentiment must be angry, sad, neutral, satisfied, or happy")
    return mapped


def valence(label: str, score: float) -> float:
    """Map a discrete label plus intensity onto [0, 1] (angry → happy)."""
    clamped = min(max(score, 0.0), 1.0)
    base = _BASE_VALENCE.get(label, 0.5)
    return round(0.5 + (base - 0.5) * clamped, 4)


def delta_and_trajectory(
    start_label: str, start_score: float, end_label: str, end_score: float
) -> tuple[float, SentimentTrajectory]:
    delta = round(valence(end_label, end_score) - valence(start_label, start_score), 3)
    if delta > TRAJECTORY_THRESHOLD:
        return delta, "improved"
    if delta < -TRAJECTORY_THRESHOLD:
        return delta, "worsened"
    return delta, "stable"


def caller_trajectory(profile: dict[str, Any] | None) -> SentimentTrajectory | None:
    if not profile:
        return None
    text = profile.get("text") if isinstance(profile.get("text"), dict) else None
    caller = text.get("caller") if text else None
    if not isinstance(caller, dict):
        return None
    value = caller.get("trajectory")
    if value in TRAJECTORIES:
        return cast(SentimentTrajectory, value)
    return None


def merge_sentiment_profile(
    existing: dict[str, Any] | None,
    *,
    text: dict[str, Any] | None = None,
    voice: dict[str, Any] | None = None,
    voice_model: str | None = None,
) -> dict[str, Any]:
    """Update one sentiment source without discarding the other source."""
    merged = dict(existing) if isinstance(existing, dict) else {}
    if text is not None:
        merged["text"] = text
    if voice is not None:
        merged["voice"] = voice
    if voice_model is not None:
        merged["voice_model"] = voice_model
    return merged
