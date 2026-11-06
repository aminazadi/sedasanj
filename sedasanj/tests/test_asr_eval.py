from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "asr_eval.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("asr_eval", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["asr_eval"] = module
    spec.loader.exec_module(module)
    return module


asr_eval = _load_script()


def test_edit_distance_counts_substitution_insertion_and_deletion() -> None:
    assert asr_eval.edit_distance(["a", "b", "c"], ["a", "x", "c"]) == 1
    assert asr_eval.edit_distance(["a", "b"], ["a", "b", "c"]) == 1
    assert asr_eval.edit_distance(["a", "b", "c"], ["a", "c"]) == 1
    assert asr_eval.edit_distance([], ["a", "b"]) == 2
    assert asr_eval.edit_distance(["a"], []) == 1


def test_scoring_normalisation_ignores_script_variants_and_punctuation() -> None:
    reference = "سلام، شماره ۱۲۳ می‌خواهم."
    hypothesis = "سلام شماره 123 مي خواهم"
    assert asr_eval.normalize_for_scoring(reference) == asr_eval.normalize_for_scoring(hypothesis)
    score = asr_eval.score_clip("c", reference, hypothesis)
    assert score.word_errors == 0 and score.wer == 0.0


def test_wer_and_cer_are_computed_on_normalised_text() -> None:
    score = asr_eval.score_clip("c", "یک دو سه چهار", "یک دو پنج چهار")
    assert (score.ref_words, score.word_errors) == (4, 1)
    assert score.wer == 0.25
    assert score.char_errors > 0


def test_corpus_wer_weights_by_reference_length() -> None:
    short = asr_eval.score_clip("a", "الف", "ب", ("t1",))
    long = asr_eval.score_clip(
        "b", "یک دو سه چهار پنج شش هفت هشت نه ده", "یک دو سه چهار پنج شش هفت هشت نه ده", ("t2",)
    )
    summary = asr_eval.summarize([short, long])
    assert summary.wer == pytest.approx(1 / 11)
    assert summary.by_tag == {"t1": 1.0, "t2": 0.0}


def _write(tmp_path: Path, name: str, data: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


MANIFEST = {
    "clips": [{"id": "a", "reference": "سلام دنیا"}, {"id": "b", "reference": "خدا نگهدار"}]
}


def test_missing_hypothesis_is_an_error_not_a_free_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write(tmp_path, "m.json", MANIFEST)
    hyp = _write(tmp_path, "h.json", {"a": "سلام دنیا"})

    assert asr_eval.main(["score", str(manifest), str(hyp)]) == 2
    assert "no hypothesis" in capsys.readouterr().err


def test_duplicate_clip_ids_are_rejected(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path,
        "m.json",
        {"clips": [{"id": "a", "reference": "x"}, {"id": "a", "reference": "y"}]},
    )
    with pytest.raises(asr_eval.EvalInputError, match="duplicate"):
        asr_eval.load_manifest(manifest)


def test_compare_passes_within_delta_and_fails_beyond(tmp_path: Path) -> None:
    manifest = _write(tmp_path, "m.json", MANIFEST)
    baseline = _write(tmp_path, "base.json", {"a": "سلام دنیا", "b": "خدا نگهدار"})
    close = _write(tmp_path, "close.json", {"a": "سلام دنیا", "b": "خدا نگه"})
    worse = _write(tmp_path, "worse.json", {"a": "سلام", "b": "خدا"})

    assert (
        asr_eval.main(["compare", str(manifest), str(baseline), str(close), "--max-delta", "0.3"])
        == 0
    )
    assert (
        asr_eval.main(["compare", str(manifest), str(baseline), str(close), "--max-delta", "0.1"])
        == 1
    )
    assert asr_eval.main(["compare", str(manifest), str(baseline), str(worse)]) == 1


def test_score_writes_json_report(tmp_path: Path) -> None:
    manifest = _write(tmp_path, "m.json", MANIFEST)
    hyp = _write(tmp_path, "sys.json", {"a": "سلام دنیا", "b": "خدا"})
    out = tmp_path / "report.json"

    assert asr_eval.main(["score", str(manifest), str(hyp), "--json", str(out)]) == 0

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["sys"]["clips"] == 2
    assert report["sys"]["wer"] == pytest.approx(1 / 4)


# --- Phase 0 extensions: S/D/I, hallucination, cpWER, timing, tag gates -----------------------


def test_align_counts_splits_substitutions_deletions_insertions() -> None:
    assert asr_eval.align_counts(["a", "b", "c"], ["a", "x", "c"]) == (1, 0, 0)
    assert asr_eval.align_counts(["a", "b", "c"], ["a", "c"]) == (0, 1, 0)
    assert asr_eval.align_counts(["a", "c"], ["a", "b", "c"]) == (0, 0, 1)
    assert asr_eval.align_counts([], ["a", "b"]) == (0, 0, 2)
    assert asr_eval.align_counts(["a", "b"], []) == (0, 2, 0)


@pytest.mark.parametrize(
    ("ref", "hyp"),
    [("a b c d e", "b x d e f g"), ("a a b", "a b b b"), ("x y z", "z y x")],
)
def test_align_counts_total_equals_edit_distance(ref: str, hyp: str) -> None:
    r, h = ref.split(), hyp.split()
    assert sum(asr_eval.align_counts(r, h)) == asr_eval.edit_distance(r, h)


def test_clip_score_reports_sdi() -> None:
    score = asr_eval.score_clip("c", "یک دو سه چهار", "یک پنج سه چهار شش")
    assert (score.substitutions, score.deletions, score.insertions) == (1, 0, 1)
    assert score.word_errors == 2


def test_non_speech_clip_counts_hallucination_and_stays_out_of_wer() -> None:
    speech = asr_eval.score_clip("a", "سلام دنیا", "سلام دنیا", ("clean",))
    silent = asr_eval.score_clip("b", "", "ممنون که تماشا کردید", ("silence",))
    quiet = asr_eval.score_clip("c", "", "", ("non-speech",))
    assert silent.hallucinated_words == 4 and quiet.hallucinated_words == 0

    summary = asr_eval.summarize([speech, silent, quiet])
    assert summary.wer == 0.0 and summary.ref_words == 2
    assert (summary.non_speech_clips, summary.hallucinated_words) == (2, 4)
    assert summary.hallucinated_clips == 1
    assert "silence" not in summary.by_tag


SPEAKER_REF = [
    {"speaker": "A", "text": "یک دو سه"},
    {"speaker": "B", "text": "چهار پنج شش"},
]


def test_cpwer_is_invariant_to_speaker_label_order() -> None:
    swapped = {"X": "چهار پنج شش", "Y": "یک دو سه"}
    score = asr_eval.score_clip("c", SPEAKER_REF, swapped)
    assert (score.cp_errors, score.cp_ref_words) == (0, 6)


def test_cpwer_penalises_speaker_confusion_but_plain_wer_does_not() -> None:
    mixed = {"A": "یک دو شش", "B": "چهار پنج سه"}
    score = asr_eval.score_clip("c", SPEAKER_REF, mixed)
    assert score.cp_errors == 2


def test_cpwer_single_stream_hypothesis_and_missing_or_extra_speakers() -> None:
    plain = asr_eval.score_clip("c", SPEAKER_REF, "یک دو سه چهار پنج شش")
    # One merged stream matches one speaker: the other speaker's 3 words are missed and the
    # merged stream carries 3 extra words.
    assert (plain.cp_errors, plain.cp_ref_words) == (6, 6)
    extra = asr_eval.score_clip(
        "c", SPEAKER_REF, {"A": "یک دو سه", "B": "چهار پنج شش", "C": "اضافه"}
    )
    assert extra.cp_errors == 1  # invented speaker costs its words


def test_cpwer_rejects_too_many_speakers() -> None:
    many = {str(i): "کلمه" for i in range(9)}
    with pytest.raises(asr_eval.EvalInputError, match="at most"):
        asr_eval.cp_word_errors(many, {"a": "x"})


def test_plain_string_reference_has_no_cpwer() -> None:
    score = asr_eval.score_clip("c", "سلام دنیا", "سلام")
    assert score.cp_errors is None
    assert asr_eval.summarize([score]).cpwer is None


def test_malformed_speaker_segments_are_input_errors(tmp_path: Path) -> None:
    manifest = _write(tmp_path, "m.json", {"clips": [{"id": "a", "reference": [{"text": "x"}]}]})
    with pytest.raises(asr_eval.EvalInputError, match="speaker"):
        asr_eval.load_manifest(manifest)


def test_unknown_tag_warns_but_known_and_parametric_tags_do_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tags = ["codeswitch", "lavalier", "table", "snr-10", "ovl-20", "silence", "bogus"]
    manifest = _write(tmp_path, "m.json", {"clips": [{"id": "a", "reference": "x", "tags": tags}]})
    asr_eval.load_manifest(manifest)
    assert "['bogus']" in capsys.readouterr().err


def test_timing_sidecar_is_reported_in_score_json(tmp_path: Path) -> None:
    manifest = _write(tmp_path, "m.json", MANIFEST)
    hyp = _write(tmp_path, "sys.json", {"a": "سلام دنیا", "b": "خدا نگهدار"})
    _write(
        tmp_path,
        "sys.latency.json",
        {
            "a": {"audio_seconds": 10, "processing_seconds": 5, "final_latency_seconds": 1.0},
            "b": {"audio_seconds": 30, "processing_seconds": 6, "final_latency_seconds": 2.0},
        },
    )
    out = tmp_path / "r.json"
    assert asr_eval.main(["score", str(manifest), str(hyp), "--json", str(out)]) == 0
    timing = json.loads(out.read_text(encoding="utf-8"))["sys"]["timing"]
    assert timing["rtf"] == pytest.approx(11 / 40)
    assert timing["final_latency_mean"] == pytest.approx(1.5)
    assert timing["final_latency_p95"] == pytest.approx(2.0)


def test_incomplete_or_invalid_timing_sidecar_is_an_error(tmp_path: Path) -> None:
    manifest = _write(tmp_path, "m.json", MANIFEST)
    hyp = _write(tmp_path, "sys.json", {"a": "سلام دنیا", "b": "خدا نگهدار"})
    sidecar = tmp_path / "sys.latency.json"
    sidecar.write_text(
        json.dumps({"a": {"audio_seconds": 10, "processing_seconds": 5}}), encoding="utf-8"
    )
    assert asr_eval.main(["score", str(manifest), str(hyp)]) == 2
    sidecar.write_text(json.dumps({"a": {"audio_seconds": 0, "processing_seconds": 1}}))
    assert asr_eval.main(["score", str(manifest), str(hyp)]) == 2


TAGGED = {
    "clips": [
        {"id": "c", "reference": "یک دو سه چهار", "tags": ["clean"]},
        {"id": "n", "reference": "یک دو سه چهار", "tags": ["noisy"]},
    ]
}


def _compare(tmp_path: Path, base: dict[str, str], cand: dict[str, str], *flags: str) -> int:
    return int(
        asr_eval.main(
            [
                "compare",
                str(_write(tmp_path, "m.json", TAGGED)),
                str(_write(tmp_path, "b.json", base)),
                str(_write(tmp_path, "c.json", cand)),
                *flags,
            ]
        )
    )


def test_compare_blocks_any_clean_regression_even_within_overall_delta(tmp_path: Path) -> None:
    base = {"c": "یک دو سه چهار", "n": "یک دو سه"}
    cand = {"c": "یک دو سه", "n": "یک دو سه چهار"}  # clean worse, noisy better
    assert _compare(tmp_path, base, cand, "--max-delta", "0.5") == 1
    assert _compare(tmp_path, base, cand, "--max-delta", "0.5", "--max-clean-delta", "0.3") == 0


def test_compare_requires_noisy_improvement_when_asked(tmp_path: Path) -> None:
    base = {"c": "یک دو سه چهار", "n": "یک دو سه"}  # noisy WER 25%
    same = dict(base)
    better = {"c": "یک دو سه چهار", "n": "یک دو سه چهار"}  # noisy WER 0
    assert _compare(tmp_path, base, same) == 0
    assert _compare(tmp_path, base, same, "--noisy-min-gain", "0.15") == 1
    assert _compare(tmp_path, base, better, "--noisy-min-gain", "0.15") == 0
    worse = {"c": "یک دو سه چهار", "n": "یک"}
    assert _compare(tmp_path, base, worse, "--max-delta", "1.0") == 1


def test_compare_overlap_gate_uses_cpwer_when_available() -> None:
    ref = SPEAKER_REF
    tags = ("overlap",)
    base = asr_eval.summarize([asr_eval.score_clip("o", ref, "یک دو سه چهار پنج شش", tags)])
    cand = asr_eval.summarize(
        [asr_eval.score_clip("o", ref, {"A": "یک دو سه", "B": "چهار پنج شش"}, tags)]
    )
    assert base.wer == 0.0  # plain WER sees nothing wrong with the merged transcript
    failures = asr_eval.compare_summaries(
        base, cand, max_delta=1.0, max_clean_delta=0.0, noisy_min_gain=0.0
    )
    assert failures == []  # cpWER improved from 50% to 0%
    reverse = asr_eval.compare_summaries(
        cand, base, max_delta=1.0, max_clean_delta=0.0, noisy_min_gain=0.0
    )
    assert len(reverse) == 1 and "cpWER" in reverse[0]
