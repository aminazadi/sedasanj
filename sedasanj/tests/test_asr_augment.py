from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


aug = _load("asr_augment")
asr_eval = _load("asr_eval")
RATE = aug.SAMPLE_RATE


def _tone(seconds: float, freq: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return amp * np.sin(2 * np.pi * freq * t)


def _snr_db(clean: np.ndarray, mixed: np.ndarray) -> float:
    """SNR of `mixed` w.r.t. `clean`, invariant to the overall gain the peak limiter may apply."""
    gain = float(np.dot(mixed, clean) / np.dot(clean, clean))
    return 20 * float(np.log10(aug.rms(gain * clean) / aug.rms(mixed - gain * clean)))


@pytest.mark.parametrize("snr", [20, 10, 5, 0])
def test_mix_at_snr_hits_the_requested_snr(snr: int) -> None:
    speech = _tone(2.0, 220)
    noise = aug.pink_noise(len(speech), np.random.default_rng(1))
    assert _snr_db(speech, aug.mix_at_snr(speech, noise, snr)) == pytest.approx(snr, abs=0.2)


def test_mix_at_snr_never_clips_and_rejects_silence() -> None:
    loud = _tone(1.0, 220, amp=0.95)
    noise = aug.pink_noise(len(loud), np.random.default_rng(1))
    assert float(np.max(np.abs(aug.mix_at_snr(loud, noise, 0)))) <= 0.99 + 1e-9
    with pytest.raises(aug.AugmentError, match="silent"):
        aug.mix_at_snr(np.zeros(100), noise[:100], 10)


def test_reverberate_keeps_length_and_level_and_changes_the_signal() -> None:
    speech = _tone(1.0, 300)
    rir = aug.synthetic_rir(np.random.default_rng(2))
    wet = aug.reverberate(speech, rir)
    assert len(wet) == len(speech)
    assert aug.rms(wet) == pytest.approx(aug.rms(speech), rel=0.02)
    assert not np.allclose(wet, speech)


@pytest.mark.parametrize("percent", [0, 10, 20, 40])
def test_overlap_mix_covers_the_requested_share_of_the_first_clip(percent: int) -> None:
    first, second = _tone(10.0, 200), _tone(10.0, 400, amp=0.1)
    mixed = aug.overlap_mix(first, second, percent)
    overlap = round(len(first) * percent / 100)
    assert len(mixed) == len(first) + len(second) - overlap
    start = len(first) - overlap
    # Outside the overlap each clip is alone, so the second clip has the same RMS as the first.
    assert aug.rms(mixed[: max(start - 1, 1)]) == pytest.approx(aug.rms(first), rel=0.02)
    assert aug.rms(mixed[len(first) :]) == pytest.approx(aug.rms(first), rel=0.05) or percent == 0


def test_overlap_is_capped_by_the_second_clip_and_validated() -> None:
    mixed = aug.overlap_mix(_tone(10.0, 200), _tone(1.0, 400), 40)
    assert len(mixed) == 10 * RATE  # 1 s of overlap at most, second ends inside the first
    with pytest.raises(aug.AugmentError, match="0-100"):
        aug.overlap_mix(_tone(1.0, 200), _tone(1.0, 400), 150)


def _make_set(tmp_path: Path) -> tuple[Path, list[dict[str, object]]]:
    clips: list[dict[str, object]] = []
    for i, (freq, ref) in enumerate([(220, "یک دو سه"), (330, "چهار پنج شش")]):
        sf.write(str(tmp_path / f"c{i}.wav"), _tone(3.0, freq), RATE, subtype="PCM_16")
        clips.append({"id": f"c{i}", "audio": f"c{i}.wav", "reference": ref, "tags": ["clean"]})
    clips.append({"id": "sil", "audio": "x.wav", "reference": "", "tags": ["silence"]})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"clips": clips}, ensure_ascii=False), encoding="utf-8")
    return manifest, clips


def test_cli_writes_audio_and_a_manifest_that_asr_eval_scores(tmp_path: Path) -> None:
    manifest, _ = _make_set(tmp_path)
    out = tmp_path / "out"
    assert aug.main([str(manifest), str(out), "--seed", "7"]) == 0

    clips = asr_eval.load_manifest(out / "manifest.json")
    ids = {c["id"] for c in clips}
    # 2 speech clips x (4 SNRs + reverb + 4 overlaps); the silence clip is skipped.
    assert len(clips) == 18 and "c0__snr10" in ids and "c1__ovl20" in ids
    by_id = {c["id"]: c for c in clips}
    assert set(by_id["c0__snr10"]["tags"]) == {"snr-10", "noisy"}
    assert by_id["c0__snr20"]["tags"] == ["snr-20"]
    assert by_id["c0__rev"]["tags"] == ["rev"]
    assert by_id["c0__ovl0"]["tags"] == ["ovl-0"] and "overlap" in by_id["c0__ovl40"]["tags"]
    assert by_id["c0__ovl20"]["reference"][1] == {"speaker": "B", "text": "چهار پنج شش"}
    for clip in clips:
        data, rate = sf.read(str(out / clip["audio"]))
        assert rate == RATE and data.ndim == 1

    perfect = {
        c["id"]: (c["reference"] if isinstance(c["reference"], str) else c["reference"])
        for c in clips
    }
    hyp = tmp_path / "perfect.json"
    hyp.write_text(json.dumps(perfect, ensure_ascii=False), encoding="utf-8")
    assert asr_eval.main(["score", str(out / "manifest.json"), str(hyp)]) == 0


def test_output_is_deterministic_per_seed_and_independent_of_clip_order(tmp_path: Path) -> None:
    manifest, clips = _make_set(tmp_path)
    for name in ("a", "b"):
        assert aug.main([str(manifest), str(tmp_path / name), "--seed", "5", "--overlap"]) == 0
    flipped = tmp_path / "flipped.json"
    flipped.write_text(json.dumps({"clips": clips[1::-1]}, ensure_ascii=False), encoding="utf-8")
    assert aug.main([str(flipped), str(tmp_path / "c"), "--seed", "5", "--overlap"]) == 0
    assert aug.main([str(manifest), str(tmp_path / "d"), "--seed", "6", "--overlap"]) == 0

    def audio(run: str, name: str) -> np.ndarray:
        return sf.read(str(tmp_path / run / "audio" / name))[0]

    for name in ("c0__snr5.wav", "c1__rev.wav"):
        assert np.array_equal(audio("a", name), audio("b", name))
        assert np.array_equal(audio("a", name), audio("c", name))
        assert not np.array_equal(audio("a", name), audio("d", name))


def test_wrong_sample_rate_is_rejected_with_a_fix(tmp_path: Path) -> None:
    sf.write(str(tmp_path / "w.wav"), _tone(1.0, 200), 8000, subtype="PCM_16")
    with pytest.raises(aug.AugmentError, match="ffmpeg"):
        aug.read_clip(tmp_path / "w.wav")


def test_overlap_needs_two_clips_and_main_reports_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sf.write(str(tmp_path / "c0.wav"), _tone(1.0, 200), RATE, subtype="PCM_16")
    single = tmp_path / "m.json"
    single.write_text(
        json.dumps({"clips": [{"id": "c0", "audio": "c0.wav", "reference": "x", "tags": []}]})
    )
    assert aug.main([str(single), str(tmp_path / "o")]) == 2
    assert "at least 2" in capsys.readouterr().err
    assert aug.main([str(single), str(tmp_path / "o"), "--overlap", "--no-rev"]) == 0
