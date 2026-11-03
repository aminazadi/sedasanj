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
