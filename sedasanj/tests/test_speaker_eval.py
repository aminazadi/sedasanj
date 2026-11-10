from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "speaker_eval.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("speaker_eval", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["speaker_eval"] = module
    spec.loader.exec_module(module)
    return module


speaker_eval = _load_script()

Row = tuple[float, float, str]


def _truth(rows: list[Row]) -> list[dict[str, Any]]:
    return [{"start": a, "end": b, "speaker": s} for a, b, s in rows]


def _hyp_entry(rows: list[tuple[float, float, str, str | None]]) -> dict[str, Any]:
    return {"segments": [{"start": a, "end": b, "speaker": s, "person": p} for a, b, s, p in rows]}


def _write_set(tmp_path: Path, truth: list[Row], enrolled: list[str], name: str = "m1") -> Path:
    (tmp_path / "truth").mkdir(exist_ok=True)
    (tmp_path / "audio").mkdir(exist_ok=True)
    (tmp_path / "audio" / f"{name}.wav").write_bytes(b"")
    (tmp_path / "truth" / f"{name}.json").write_text(json.dumps(_truth(truth)))
    for person in enrolled:
        (tmp_path / f"{person}.wav").write_bytes(b"")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "enrolled": {p: f"{p}.wav" for p in enrolled},
                "meetings": [
                    {
                        "id": name,
                        "audio": f"audio/{name}.wav",
                        "truth": f"truth/{name}.json",
                    }
                ],
            }
        )
    )
    return manifest


def _write_hyp(
    tmp_path: Path, rows: list[tuple[float, float, str, str | None]], file: str = "h.json"
) -> Path:
    path = tmp_path / file
    path.write_text(json.dumps({"variant": file, "meetings": {"m1": _hyp_entry(rows)}}))
    return path


def _pooled(tmp_path: Path, manifest: Path, hyp: Path) -> dict[str, float | None]:
    loaded = speaker_eval.load_manifest(manifest)
    per_meeting = speaker_eval.score_system(loaded, hyp)
    return speaker_eval.metrics(
        speaker_eval._sum([b for blocks in per_meeting.values() for b in blocks])
    )


TWO_SPEAKERS: list[Row] = [(0.0, 10.0, "Ali"), (10.0, 20.0, "Sara")]


def test_perfect_system_has_zero_der_and_full_naming(tmp_path: Path) -> None:
    manifest = _write_set(tmp_path, TWO_SPEAKERS, ["Ali", "Sara"])
    hyp = _write_hyp(tmp_path, [(0, 10, "Ali", "Ali"), (10, 20, "Sara", "Sara")])
    m = _pooled(tmp_path, manifest, hyp)
    assert m["der"] == pytest.approx(0.0)
    assert m["id_accuracy"] == pytest.approx(1.0)
    assert m["false_accept"] == pytest.approx(0.0)
    # 20 s minus the 0.25 s collars at 0 s, 10 s (twice) and 20 s.
    assert m["truth_speech_s"] == pytest.approx(19.0, abs=0.05)


def test_voice_labels_are_arbitrary_but_names_are_not(tmp_path: Path) -> None:
    manifest = _write_set(tmp_path, TWO_SPEAKERS, ["Ali", "Sara"])
    # Voices separated correctly (DER 0) but the two people are swapped.
    hyp = _write_hyp(tmp_path, [(0, 10, "X", "Sara"), (10, 20, "Y", "Ali")])
    m = _pooled(tmp_path, manifest, hyp)
    assert m["der"] == pytest.approx(0.0)
    assert m["id_accuracy"] == pytest.approx(0.0)
    assert m["false_accept"] == pytest.approx(1.0)


def test_missing_speech_is_counted_as_missed_and_left_unknown(tmp_path: Path) -> None:
    manifest = _write_set(tmp_path, TWO_SPEAKERS, ["Ali", "Sara"])
    hyp = _write_hyp(tmp_path, [(0, 10, "Ali", "Ali")])
    m = _pooled(tmp_path, manifest, hyp)
    assert m["der"] == pytest.approx(0.5, abs=0.01)
    assert m["missed"] == pytest.approx(0.5, abs=0.01)
    assert m["false_reject"] == pytest.approx(0.5, abs=0.01)
    assert m["false_accept"] == pytest.approx(0.0)


def test_naming_a_stranger_is_a_false_accept(tmp_path: Path) -> None:
    manifest = _write_set(tmp_path, [(0.0, 10.0, "Ali"), (10.0, 20.0, "Guest")], ["Ali"])
    hyp = _write_hyp(tmp_path, [(0, 20, "Ali", "Ali")])
    m = _pooled(tmp_path, manifest, hyp)
    assert m["id_accuracy"] == pytest.approx(1.0)
    assert m["false_accept"] == pytest.approx(0.5, abs=0.01)
    assert m["confusion"] == pytest.approx(0.5, abs=0.01)


def test_a_stranger_left_unknown_is_correct(tmp_path: Path) -> None:
    manifest = _write_set(tmp_path, [(0.0, 10.0, "Ali"), (10.0, 20.0, "Guest")], ["Ali"])
    hyp = _write_hyp(tmp_path, [(0, 10, "Ali", "Ali"), (10, 20, "ناشناس 1", None)])
    m = _pooled(tmp_path, manifest, hyp)
    assert m["der"] == pytest.approx(0.0)
    assert m["false_accept"] == pytest.approx(0.0)
    assert m["stranger_single_s"] == pytest.approx(9.5, abs=0.05)


def test_over_split_voice_costs_confusion(tmp_path: Path) -> None:
    manifest = _write_set(tmp_path, [(0.0, 20.0, "Ali")], ["Ali"])
    hyp = _write_hyp(tmp_path, [(0, 10, "A", "Ali"), (10, 20, "B", None)])
    m = _pooled(tmp_path, manifest, hyp)
    assert m["der"] == pytest.approx(0.5, abs=0.01)


def test_overlap_is_scored_but_not_used_for_naming(tmp_path: Path) -> None:
    truth: list[Row] = [(0.0, 10.0, "Ali"), (5.0, 15.0, "Sara")]
    manifest = _write_set(tmp_path, truth, ["Ali", "Sara"])
    both = [(0, 10, "Ali", "Ali"), (5, 15, "Sara", "Sara")]
    m = _pooled(tmp_path, manifest, _write_hyp(tmp_path, both))
    assert m["der"] == pytest.approx(0.0)
    # Only the frames where one person talks alone count for naming.
    assert m["enrolled_single_s"] == pytest.approx(9.0, abs=0.05)

    # Hearing nobody during the overlap shows up as missed speech.
    no_overlap = [(0, 10, "Ali", "Ali"), (10, 15, "Sara", "Sara")]
    m = _pooled(tmp_path, manifest, _write_hyp(tmp_path, no_overlap, "h2.json"))
    assert m["missed"] is not None and m["missed"] > 0.2


def test_assignment_finds_the_best_pairing() -> None:
    cost = [[4.0, 1.0, 3.0], [2.0, 0.0, 5.0], [3.0, 2.0, 2.0]]
    cols = speaker_eval._assign(cost)
    assert sorted(cols) == [0, 1, 2]
    assert sum(cost[i][j] for i, j in enumerate(cols)) == pytest.approx(5.0)


def _long_set(tmp_path: Path) -> tuple[Path, list[tuple[float, float, str, str | None]]]:
    rows: list[Row] = []
    good: list[tuple[float, float, str, str | None]] = []
    for i in range(30):  # 5 minutes, alternating 10 s turns
        who = "Ali" if i % 2 == 0 else "Sara"
        rows.append((i * 10.0, i * 10.0 + 10.0, who))
        good.append((i * 10.0, i * 10.0 + 10.0, who, who))
    return _write_set(tmp_path, rows, ["Ali", "Sara"]), good


def test_compare_accepts_a_wholly_better_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, good = _long_set(tmp_path)
    swap = {"Ali": "Sara", "Sara": "Ali"}
    # The baseline swaps the two people in the second half of the meeting.
    bad = [(a, b, s, p if a < 150 or p is None else swap[p]) for a, b, s, p in good]
    base = _write_hyp(tmp_path, bad, "base.json")
    cand = _write_hyp(tmp_path, good, "cand.json")
    code = speaker_eval.main(
        [
            "compare",
            str(manifest),
            str(base),
            str(cand),
            "--bootstrap",
            "400",
            "--require-better",
            "id_accuracy",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "PASS" in out


def test_compare_rejects_identical_systems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, good = _long_set(tmp_path)
    one = _write_hyp(tmp_path, good, "one.json")
    two = _write_hyp(tmp_path, good, "two.json")
    code = speaker_eval.main(["compare", str(manifest), str(one), str(two), "--bootstrap", "200"])
    out = capsys.readouterr().out
    assert code == 1
    assert "REJECT" in out


def test_compare_rejects_a_candidate_that_names_strangers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows: list[Row] = []
    base_rows: list[tuple[float, float, str, str | None]] = []
    cand_rows: list[tuple[float, float, str, str | None]] = []
    for i in range(30):
        who = "Ali" if i % 2 == 0 else "Guest"
        rows.append((i * 10.0, i * 10.0 + 10.0, who))
        base_rows.append((i * 10.0, i * 10.0 + 10.0, who, "Ali" if who == "Ali" else None))
        # Better DER is not enough when strangers get a person's name.
        cand_rows.append((i * 10.0, i * 10.0 + 10.0, "Ali", "Ali"))
    manifest = _write_set(tmp_path, rows, ["Ali"])
    base = _write_hyp(tmp_path, base_rows, "base.json")
    cand = _write_hyp(tmp_path, cand_rows, "cand.json")
    code = speaker_eval.main(["compare", str(manifest), str(base), str(cand), "--bootstrap", "200"])
    out = capsys.readouterr().out
    assert code == 1
    assert "wrong names may have risen" in out


def test_validate_reports_missing_truth_and_draft_writes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write_set(tmp_path, TWO_SPEAKERS, ["Ali", "Sara"])
    (tmp_path / "truth" / "m1.json").unlink()
    assert speaker_eval.main(["validate", str(manifest)]) == 1
    assert "no truth file yet" in capsys.readouterr().out

    hyp = _write_hyp(tmp_path, [(0, 10, "Ali", "Ali"), (10, 20, "ناشناس 1", None)])
    out_dir = tmp_path / "drafts"
    assert speaker_eval.main(["draft", str(manifest), str(hyp), str(out_dir)]) == 0
    draft = json.loads((out_dir / "draft-m1.json").read_text(encoding="utf-8"))
    assert [d["speaker"] for d in draft] == ["Ali", "ناشناس 1"]
    assert "[00:00-00:10] Ali" in (out_dir / "draft-m1.txt").read_text(encoding="utf-8")


def test_bad_input_exits_with_code_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = _write_set(tmp_path, TWO_SPEAKERS, ["Ali"])
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert speaker_eval.main(["score", str(manifest), str(broken)]) == 2
    assert "error:" in capsys.readouterr().err
    assert speaker_eval.main(["score", str(manifest), str(tmp_path / "none.json")]) == 2
