from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.schemas import InsightsOut
from app.sentiment import merge_sentiment_profile
from worker_emotion.engine import EmotionPrediction, parse_prediction
from worker_emotion.main import AudioWindow, build_audio_windows, build_voice_profile


def test_emotion2vec_scores_are_mapped_to_product_labels() -> None:
    prediction = parse_prediction(
        {
            "labels": [
                "angry",
                "disgusted",
                "fearful",
                "happy",
                "neutral",
                "other",
                "sad",
                "surprised",
                "unknown",
            ],
            "scores": [0.05, 0.05, 0.05, 0.7, 0.05, 0.02, 0.04, 0.02, 0.02],
        }
    )

    assert prediction.label == "happy"
    assert prediction.score == pytest.approx(0.7)
    assert sum(prediction.probabilities.values()) == pytest.approx(1.0)
    assert 0.75 < prediction.valence < 1.0


def test_emotion2vec_rejects_malformed_results() -> None:
    with pytest.raises(RuntimeError, match="aligned labels and scores"):
        parse_prediction({"labels": ["happy"], "scores": []})


def test_audio_windows_follow_speaker_turns_and_bound_long_audio() -> None:
    utterances = [
        SimpleNamespace(channel=0, t_start_ms=0, t_end_ms=3500),
        SimpleNamespace(channel=0, t_start_ms=3700, t_end_ms=9100),
        SimpleNamespace(channel=1, t_start_ms=1200, t_end_ms=2600),
    ]

    windows = build_audio_windows(
        utterances,  # type: ignore[arg-type]
        duration_ms=10_000,
        max_window_ms=4_000,
        min_window_ms=1_000,
        max_windows=10,
    )

    caller = [window for window in windows if window.channel == 0]
    agent = [window for window in windows if window.channel == 1]
    assert [(window.t_start_ms, window.t_end_ms) for window in caller] == [
        (0, 4_000),
        (4_000, 8_000),
        (8_000, 9_100),
    ]
    assert [(window.t_start_ms, window.t_end_ms) for window in agent] == [(1_200, 2_600)]


def test_voice_profile_contains_real_timeline_and_party_trajectory() -> None:
    windows = [
        AudioWindow(channel=0, t_start_ms=0, t_end_ms=4_000),
        AudioWindow(channel=0, t_start_ms=4_000, t_end_ms=8_000),
        AudioWindow(channel=1, t_start_ms=0, t_end_ms=4_000),
    ]
    predictions = [
        EmotionPrediction(
            label="angry",
            score=0.9,
            valence=0.05,
            probabilities={"angry": 0.9, "sad": 0.05, "neutral": 0.05},
        ),
        EmotionPrediction(
            label="happy",
            score=0.8,
            valence=0.9,
            probabilities={"happy": 0.8, "satisfied": 0.1, "neutral": 0.1},
        ),
        EmotionPrediction(
            label="neutral",
            score=0.8,
            valence=0.5,
            probabilities={"neutral": 0.8, "happy": 0.1, "sad": 0.1},
        ),
    ]

    profile = build_voice_profile(windows, predictions)

    assert profile is not None
    assert profile.caller.trajectory == "improved"
    assert len(profile.caller.timeline) == 2
    assert profile.agent is not None
    assert profile.agent.overall.label == "neutral"


def test_text_update_preserves_existing_voice_profile() -> None:
    voice = {"caller": {"trajectory": "stable"}, "agent": None}
    text = {"caller": {"trajectory": "improved"}, "agent": None}

    merged = merge_sentiment_profile(
        {"voice": voice, "voice_model": "iic/emotion2vec_plus_base"},
        text=text,
    )

    assert merged["voice"] == voice
    assert merged["text"] == text
    assert merged["voice_model"] == "iic/emotion2vec_plus_base"


def test_api_accepts_voice_profile_before_text_analysis_finishes() -> None:
    out = InsightsOut(
        sentiment_profile={
            "voice": {
                "caller": {
                    "start": {"label": "neutral", "score": 0.8},
                    "end": {"label": "happy", "score": 0.7},
                    "overall": {"label": "satisfied", "score": 0.6},
                    "timeline": [
                        {
                            "t_start_ms": 0,
                            "t_end_ms": 3000,
                            "label": "neutral",
                            "score": 0.8,
                            "valence": 0.5,
                        }
                    ],
                },
                "agent": None,
            },
            "voice_model": "iic/emotion2vec_plus_base",
        }
    )

    assert out.sentiment_profile is not None
    assert out.sentiment_profile.text is None
    assert out.sentiment_profile.voice is not None
    assert out.sentiment_profile.voice.caller.timeline[0].valence == 0.5
