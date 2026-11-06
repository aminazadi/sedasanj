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


def test_cli_writes_audio_and_a_manifest_that_asr_eval_scores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, _ = _make_set(tmp_path)
    out = tmp_path / "out"
    assert aug.main([str(manifest), str(out), "--seed", "7"]) == 0

    clips = asr_eval.load_manifest(out / "manifest.json")
    ids = {c["id"] for c in clips}
    # 2 speech clips x (4 SNRs + reverb + 2 quiet + 4 overlaps) + the noise-only clip; the silence
    # clip in the input is skipped. asr_eval knows every tag we wrote (it warns on unknown ones).
    assert len(clips) == 23 and "c0__snr10" in ids and "c1__ovl20" in ids and "noise-only" in ids
    assert "unknown tag" not in capsys.readouterr().err
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


@pytest.mark.parametrize("db", [6, 20, 30])
def test_attenuate_changes_only_the_level(db: int) -> None:
    speech = _tone(1.0, 300)
    quiet = aug.attenuate(speech, db)
    assert aug.rms(quiet) == pytest.approx(aug.rms(speech) * 10 ** (-db / 20), rel=1e-9)
    assert np.allclose(quiet * 10 ** (db / 20), speech)


def test_attenuate_rejects_a_negative_attenuation() -> None:
    with pytest.raises(aug.AugmentError, match="0 dB or more"):
        aug.attenuate(_tone(0.1, 200), -3)


def test_noise_only_track_has_the_noise_level_of_the_matching_snr_variant() -> None:
    speech = _tone(2.0, 220, amp=0.1)  # quiet enough that the peak limiter never acts
    noise = aug.pink_noise(len(speech), np.random.default_rng(1))
    mixed = aug.mix_at_snr(speech, noise, 5)
    track = aug.noise_only_track(noise, aug.rms(speech), 5)
    assert aug.rms(track) == pytest.approx(aug.rms(mixed - speech), rel=1e-6)
    assert aug.rms(speech) / aug.rms(track) == pytest.approx(10 ** (5 / 20), rel=1e-6)


def test_noise_only_track_rejects_silence_and_dead_noise() -> None:
    with pytest.raises(aug.AugmentError, match="silent"):
        aug.noise_only_track(np.ones(10), 0.0, 5)
    with pytest.raises(aug.AugmentError, match="zero energy"):
        aug.noise_only_track(np.zeros(10), 0.1, 5)


def test_cli_adds_quiet_copies_and_a_noise_only_clip(tmp_path: Path) -> None:
    manifest, _ = _make_set(tmp_path)
    out = tmp_path / "out"
    assert aug.main([str(manifest), str(out), "--seed", "7", "--noise-only", "10"]) == 0

    by_id = {c["id"]: c for c in asr_eval.load_manifest(out / "manifest.json")}
    # `clean` is dropped (the level is not the recorded one); the reference is unchanged.
    assert set(by_id["c0__q20"]["tags"]) == {"quiet-20", "quiet"}
    assert set(by_id["c1__q30"]["tags"]) == {"quiet-30", "quiet"}
    assert by_id["c0__q20"]["reference"] == "یک دو سه"
    original = _tone(3.0, 220)
    quiet = sf.read(str(out / by_id["c0__q20"]["audio"]))[0]
    assert aug.rms(quiet) / aug.rms(original) == pytest.approx(0.1, rel=0.01)

    noise_only = by_id["noise-only"]
    assert noise_only["reference"] == "" and set(noise_only["tags"]) == {"non-speech", "noise-only"}
    track = sf.read(str(out / noise_only["audio"]))[0]
    assert len(track) == 10 * RATE
    # As loud as the noise in the snr-5 variants: the mean speech level 5 dB down.
    assert aug.rms(track) == pytest.approx(aug.rms(original) / 10 ** (5 / 20), rel=0.02)


def test_cli_can_skip_the_quiet_copies_and_the_noise_only_clip(tmp_path: Path) -> None:
    manifest, _ = _make_set(tmp_path)
    out = tmp_path / "out"
    args = [str(manifest), str(out), "--quiet", "--noise-only", "0", "--overlap"]
    assert aug.main(args) == 0
    ids = {c["id"] for c in asr_eval.load_manifest(out / "manifest.json")}
    assert len(ids) == 2 * (4 + 1)
    assert "noise-only" not in ids and not any("__q" in clip_id for clip_id in ids)


def test_noise_only_clip_is_deterministic_and_built_from_the_given_noise(tmp_path: Path) -> None:
    manifest, _ = _make_set(tmp_path)
    room = aug.pink_noise(RATE, np.random.default_rng(3)) * 0.1
    noise_path = tmp_path / "room.wav"
    sf.write(str(noise_path), room, RATE, subtype="PCM_16")
    for name, seed in (("a", "5"), ("b", "5"), ("c", "6")):
        args = [str(manifest), str(tmp_path / name), "--seed", seed, "--overlap", "--no-rev"]
        assert aug.main([*args, "--noise", str(noise_path)]) == 0

    def track(run: str) -> np.ndarray:
        return sf.read(str(tmp_path / run / "audio" / "noise-only.wav"))[0]

    assert np.array_equal(track("a"), track("b"))
    assert not np.array_equal(track("a"), track("c"))  # another seed starts elsewhere in the noise
    assert len(track("a")) == 30 * RATE  # a 1 s recording is looped to the default 30 s


def test_keep_originals_copies_every_input_clip_unchanged_ahead_of_its_variants(
    tmp_path: Path,
) -> None:
    manifest, _ = _make_set(tmp_path)
    sf.write(str(tmp_path / "x.wav"), np.zeros(RATE), RATE, subtype="PCM_16")  # the silence clip
    out = tmp_path / "out"
    args = [str(manifest), str(out), "--keep-originals", "--noise-only", "0"]
    assert aug.main([*args, "--quiet", "--overlap", "--no-rev", "--snr", "10"]) == 0

    produced = asr_eval.load_manifest(out / "manifest.json")
    assert [c["id"] for c in produced] == ["c0", "c1", "sil", "c0__snr10", "c1__snr10"]
    by_id = {c["id"]: c for c in produced}
    assert by_id["c0"]["tags"] == ["clean"] and by_id["c0"]["reference"] == "یک دو سه"
    assert by_id["sil"]["tags"] == ["silence"] and by_id["sil"]["reference"] == ""
    assert np.array_equal(
        sf.read(str(out / by_id["c0"]["audio"]))[0], sf.read(str(tmp_path / "c0.wav"))[0]
    )


def test_a_clip_that_would_reuse_a_generated_id_is_rejected_with_a_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, clips = _make_set(tmp_path)
    clips[0]["id"] = "noise-only"  # the id the generated noise-only clip takes
    manifest.write_text(json.dumps({"clips": clips[:2]}, ensure_ascii=False), encoding="utf-8")
    args = [str(manifest), str(tmp_path / "o"), "--keep-originals", "--overlap", "--no-rev"]
    assert aug.main(args) == 2
    assert "rename the input clip" in capsys.readouterr().err


def test_negative_noise_only_length_is_rejected_with_a_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, _ = _make_set(tmp_path)
    assert aug.main([str(manifest), str(tmp_path / "o"), "--noise-only", "-5"]) == 2
    assert "0 (skip it)" in capsys.readouterr().err


def test_words_on_the_noise_only_clip_count_as_hallucination() -> None:
    score = asr_eval.score_clip("noise-only", "", "ممنون از شما", ("non-speech", "noise-only"))
    assert score.hallucinated_words == 3
    assert asr_eval.unknown_tags(["quiet-20", "quiet", "noise-only", "snr-5", "ovl-10"]) == []


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
