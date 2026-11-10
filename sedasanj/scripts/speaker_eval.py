#!/usr/bin/env python3
"""Score speaker diarization and speaker naming against human labels, and compare systems.

Standard library only (no numpy), so it runs anywhere, like ``asr_eval.py``.

Evaluation set layout (see sedasanj/test_data/speaker_eval/README.md). Audio, truth and
hypotheses stay out of git:

    manifest.json   {"enrolled": {"Ali": "enroll/ali.wav", ...},
                     "meetings": [{"id": "m1", "audio": "audio/m1.wav",
                                   "truth": "truth/m1.json",
                                   "attendees": ["Ali", "Sara"],      # optional
                                   "tags": ["overlap", "noisy"]}]}    # optional
    truth/<id>.json [{"start": 0.0, "end": 3.2, "speaker": "Ali"}, ...]
                    seconds; segments of different speakers may overlap. A speaker who is
                    not in "enrolled" is someone the app has never heard (it must stay
                    "unknown", never get a person's name).

Hypotheses, one file per system (written by test/bench/bench_speaker_test.dart):

    <system>.json   {"variant": "...", "meetings": {"m1": {"segments": [
                       {"start": 0.0, "end": 3.1, "speaker": "Ali", "person": "Ali"},
                       {"start": 3.2, "end": 5.0, "speaker": "ناشناس 1", "person": null}],
                     "timing": {...}}}}
                    ``speaker`` is the label of one voice (used for DER); ``person`` is the
                    enrolled person's name or null when the voice stayed unknown.

Metrics (10 ms frames; 0.25 s collar around every truth boundary is ignored):

    DER             (missed + false alarm + confusion) / truth speech, with the optimal
                    one-to-one mapping of hypothesis voices to truth speakers.
    id_accuracy     of the frames where one enrolled person speaks alone, the share where
                    the system named that person.
    false_accept    share of single-speaker frames where a person was named who was not
                    speaking (an enrolled person named wrongly, or a stranger given a name).
                    A wrong name is worse than "unknown", so it is reported on its own.
    false_reject    of the same enrolled frames, the share left "unknown".

Usage:
    speaker_eval.py validate MANIFEST
    speaker_eval.py score    MANIFEST HYP.json [HYP2.json ...] [--json OUT]
    speaker_eval.py compare  MANIFEST BASELINE.json CANDIDATE.json
                             [--bootstrap 2000] [--seed 1234]
                             [--require-better der|id_accuracy|false_accept]
                             [--max-false-accept-rise 0.005]
    speaker_eval.py draft    MANIFEST HYP.json OUT_DIR     # a draft truth to correct by hand

`compare` resamples 30 s blocks of the meetings (paired: the same blocks for both systems).
It exits 0 when the candidate is wholly better on ``--require-better`` (95% interval) and
false accepts did not rise beyond ``--max-false-accept-rise`` (upper end of the interval),
1 otherwise, 2 on unusable input. With few meetings the interval is wide: "not wholly better"
means "unknown", not "no effect".
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FRAME = 0.01  # seconds
COLLAR = 0.25  # seconds on each side of a truth boundary
BLOCK_FRAMES = 3000  # 30 s

# Order of the per-block statistics vector.
STAT_KEYS = (
    "ref",  # truth speaker-seconds (a frame with two talkers counts twice)
    "miss",
    "fa",
    "conf",
    "id_total",  # frames with one enrolled person speaking alone
    "id_ok",
    "id_wrong",
    "id_unknown",
    "imp_total",  # frames with one not-enrolled person speaking alone
    "imp_named",
)


class InputError(Exception):
    """Unusable manifest, truth or hypothesis (exit code 2)."""


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    speaker: str
    person: str | None = None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"Not valid JSON: {path} ({exc})") from exc


def _segments(raw: Any, where: str, *, hypothesis: bool) -> list[Segment]:
    if not isinstance(raw, list):
        raise InputError(f"{where}: expected a list of segments")
    out: list[Segment] = []
    for i, item in enumerate(raw):
        try:
            start = float(item["start"])
            end = float(item["end"])
            speaker = str(item["speaker"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError(f"{where}[{i}]: needs start, end and speaker") from exc
        if end <= start or start < 0:
            raise InputError(f"{where}[{i}]: bad span {start}..{end}")
        person = item.get("person") if hypothesis else None
        out.append(Segment(start, end, speaker, None if person is None else str(person)))
    return out


@dataclass(frozen=True)
class Meeting:
    id: str
    truth: list[Segment]
    tags: tuple[str, ...]

    @property
    def duration(self) -> float:
        return max((s.end for s in self.truth), default=0.0)


@dataclass(frozen=True)
class Manifest:
    root: Path
    enrolled: dict[str, str]
    meetings: list[Meeting]


def load_manifest(path: Path, *, need_truth: bool = True) -> Manifest:
    """With ``need_truth=False`` a meeting without a truth file gets an empty truth
    (used by ``draft``, which writes the first truth, and by ``validate``)."""
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("meetings"), list):
        raise InputError(f"{path}: expected an object with a 'meetings' list")
    enrolled = data.get("enrolled", {})
    if not isinstance(enrolled, dict):
        raise InputError(f"{path}: 'enrolled' must be an object name -> wav path")
    meetings: list[Meeting] = []
    seen: set[str] = set()
    for entry in data["meetings"]:
        mid = str(entry.get("id", ""))
        if not mid or mid in seen:
            raise InputError(f"{path}: meeting id missing or repeated: {mid!r}")
        seen.add(mid)
        truth_path = path.parent / str(entry.get("truth", ""))
        if not need_truth and not truth_path.is_file():
            truth: list[Segment] = []
        else:
            truth = _segments(_read_json(truth_path), str(truth_path), hypothesis=False)
        meetings.append(Meeting(mid, truth, tuple(entry.get("tags", ()))))
    if not meetings:
        raise InputError(f"{path}: no meetings")
    return Manifest(path.parent, {str(k): str(v) for k, v in enrolled.items()}, meetings)


def load_hypothesis(path: Path, meetings: list[Meeting]) -> dict[str, list[Segment]]:
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("meetings"), dict):
        raise InputError(f"{path}: expected an object with a 'meetings' object")
    out: dict[str, list[Segment]] = {}
    for meeting in meetings:
        entry = data["meetings"].get(meeting.id)
        if entry is None:
            raise InputError(f"{path}: no hypothesis for meeting {meeting.id!r}")
        out[meeting.id] = _segments(entry.get("segments"), f"{path}:{meeting.id}", hypothesis=True)
    return out


def _mask(segments: list[Segment], key: Any, frames: int) -> dict[str, bytearray]:
    masks: dict[str, bytearray] = {}
    for seg in segments:
        label = key(seg)
        if label is None:
            continue
        mask = masks.setdefault(label, bytearray(frames))
        a = max(0, round(seg.start / FRAME))
        b = min(frames, round(seg.end / FRAME))
        if b > a:
            mask[a:b] = b"\x01" * (b - a)
    return masks


def _assign(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment (Hungarian). Square matrix; returns column per row."""
    n = len(cost)
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    result = [0] * n
    for j in range(1, n + 1):
        result[p[j] - 1] = j - 1
    return result


def _best_mapping(
    cooc: dict[tuple[str, str], int], refs: list[str], hyps: list[str]
) -> dict[str, str]:
    """Hypothesis label -> truth speaker, maximising shared speech time."""
    size = max(len(refs), len(hyps))
    if size == 0:
        return {}
    cost = [[0.0] * size for _ in range(size)]
    for i, r in enumerate(refs):
        for j, h in enumerate(hyps):
            cost[i][j] = -float(cooc.get((r, h), 0))
    cols = _assign(cost)
    mapping: dict[str, str] = {}
    for i, j in enumerate(cols):
        if i < len(refs) and j < len(hyps) and cooc.get((refs[i], hyps[j]), 0) > 0:
            mapping[hyps[j]] = refs[i]
    return mapping


def score_meeting(meeting: Meeting, hyp: list[Segment], enrolled: set[str]) -> list[list[float]]:
    """Per 30 s block statistics (seconds) in the order of STAT_KEYS."""
    frames = round(meeting.duration / FRAME)
    ref_masks = _mask(meeting.truth, lambda s: s.speaker, frames)
    hyp_masks = _mask(hyp, lambda s: s.speaker, frames)
    person_masks = _mask(hyp, lambda s: s.person, frames)

    excluded = bytearray(frames)
    collar = round(COLLAR / FRAME)
    for seg in meeting.truth:
        for edge in (seg.start, seg.end):
            centre = round(edge / FRAME)
            a, b = max(0, centre - collar), min(frames, centre + collar)
            if b > a:
                excluded[a:b] = b"\x01" * (b - a)

    refs = sorted(ref_masks)
    hyps = sorted(hyp_masks)
    cooc: dict[tuple[str, str], int] = {}
    for r in refs:
        rm = ref_masks[r]
        for h in hyps:
            hm = hyp_masks[h]
            cooc[(r, h)] = sum(1 for f in range(frames) if rm[f] and hm[f] and not excluded[f])
    mapping = _best_mapping(cooc, refs, hyps)

    blocks = [[0.0] * len(STAT_KEYS) for _ in range((frames + BLOCK_FRAMES - 1) // BLOCK_FRAMES)]
    for f in range(frames):
        if excluded[f]:
            continue
        active_ref = [r for r in refs if ref_masks[r][f]]
        active_hyp = [h for h in hyps if hyp_masks[h][f]]
        n_ref, n_hyp = len(active_ref), len(active_hyp)
        row = blocks[f // BLOCK_FRAMES]
        row[0] += n_ref * FRAME
        correct = len({mapping[h] for h in active_hyp if mapping.get(h) in active_ref})
        row[1] += max(0, n_ref - n_hyp) * FRAME
        row[2] += max(0, n_hyp - n_ref) * FRAME
        row[3] += (min(n_ref, n_hyp) - correct) * FRAME
        if n_ref == 1:
            speaker = active_ref[0]
            named = {p for p, m in person_masks.items() if m[f]}
            if speaker in enrolled:
                row[4] += FRAME
                if speaker in named:
                    row[5] += FRAME
                elif named:
                    row[6] += FRAME
                else:
                    row[7] += FRAME
            else:
                row[8] += FRAME
                if named:
                    row[9] += FRAME
    return blocks


def _ratio(num: float, den: float) -> float | None:
    return None if den <= 0 else num / den


def metrics(total: list[float]) -> dict[str, float | None]:
    s = dict(zip(STAT_KEYS, total, strict=True))
    single = s["id_total"] + s["imp_total"]
    return {
        "der": _ratio(s["miss"] + s["fa"] + s["conf"], s["ref"]),
        "missed": _ratio(s["miss"], s["ref"]),
        "false_alarm": _ratio(s["fa"], s["ref"]),
        "confusion": _ratio(s["conf"], s["ref"]),
        "id_accuracy": _ratio(s["id_ok"], s["id_total"]),
        "false_accept": _ratio(s["id_wrong"] + s["imp_named"], single),
        "false_reject": _ratio(s["id_unknown"], s["id_total"]),
        "truth_speech_s": s["ref"],
        "enrolled_single_s": s["id_total"],
        "stranger_single_s": s["imp_total"],
    }


def _sum(blocks: list[list[float]]) -> list[float]:
    return [sum(col) for col in zip(*blocks, strict=True)] if blocks else [0.0] * len(STAT_KEYS)


def score_system(manifest: Manifest, hyp_path: Path) -> dict[str, list[list[float]]]:
    hyps = load_hypothesis(hyp_path, manifest.meetings)
    enrolled = set(manifest.enrolled)
    return {m.id: score_meeting(m, hyps[m.id], enrolled) for m in manifest.meetings}


def _fmt(value: float | None, *, pct: bool = True) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%" if pct else f"{value:.1f}"


def cmd_validate(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest), need_truth=False)
    problems = 0
    names = set(manifest.enrolled)
    for rel in manifest.enrolled.values():
        if not (manifest.root / rel).exists():
            print(f"missing enrolment audio: {rel}")
            problems += 1
    raw = _read_json(Path(args.manifest))
    for entry, meeting in zip(raw["meetings"], manifest.meetings, strict=True):
        audio = manifest.root / str(entry.get("audio", ""))
        if not audio.exists():
            print(f"{meeting.id}: missing audio {audio.name}")
            problems += 1
        if not meeting.truth:
            print(f"{meeting.id}: no truth file yet (run `draft`, then correct it)")
            problems += 1
            continue
        speakers = {s.speaker for s in meeting.truth}
        known = speakers & names
        print(
            f"{meeting.id}: {meeting.duration / 60:.1f} min, {len(speakers)} speakers "
            f"({len(known)} enrolled, {len(speakers - names)} strangers), "
            f"{len(meeting.truth)} segments"
        )
        if len(speakers) < 2:
            print(f"  warning: {meeting.id} has one speaker; DER and naming say little")
        if not known:
            print(f"  warning: {meeting.id} has no enrolled speaker; naming is not tested")
    print(f"{'OK' if not problems else 'PROBLEMS'}: {problems} missing file(s)")
    return 1 if problems else 0


def cmd_score(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest))
    report: dict[str, Any] = {}
    for hyp_file in args.hypotheses:
        per_meeting = score_system(manifest, Path(hyp_file))
        pooled = metrics(_sum([b for blocks in per_meeting.values() for b in blocks]))
        report[hyp_file] = {
            "pooled": pooled,
            "meetings": {mid: metrics(_sum(blocks)) for mid, blocks in per_meeting.items()},
        }
        print(f"== {hyp_file}")
        print(
            f"  pooled  DER {_fmt(pooled['der'])} (missed {_fmt(pooled['missed'])}, "
            f"false alarm {_fmt(pooled['false_alarm'])}, confusion {_fmt(pooled['confusion'])})"
        )
        print(
            f"          naming: correct {_fmt(pooled['id_accuracy'])}, "
            f"wrong name {_fmt(pooled['false_accept'])}, "
            f"left unknown {_fmt(pooled['false_reject'])}"
        )
        for mid, m in report[hyp_file]["meetings"].items():
            print(
                f"  {mid:<12} DER {_fmt(m['der'])}  correct {_fmt(m['id_accuracy'])}  "
                f"wrong name {_fmt(m['false_accept'])}"
            )
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


def _percentile(sorted_values: list[float], q: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * q)))]


def bootstrap_delta(
    base: list[list[float]],
    cand: list[list[float]],
    metric: str,
    runs: int,
    seed: int,
) -> tuple[float, float, float]:
    """Point difference (candidate - baseline) and its 95% interval, paired by block."""
    rng = random.Random(seed)
    n = len(base)
    point_b = metrics(_sum(base))[metric]
    point_c = metrics(_sum(cand))[metric]
    if point_b is None or point_c is None:
        raise InputError(f"metric {metric} is undefined (no matching speech in the set)")
    deltas: list[float] = []
    for _ in range(runs):
        idx = [rng.randrange(n) for _ in range(n)]
        b = metrics(_sum([base[i] for i in idx]))[metric]
        c = metrics(_sum([cand[i] for i in idx]))[metric]
        if b is not None and c is not None:
            deltas.append(c - b)
    deltas.sort()
    if not deltas:
        raise InputError(f"metric {metric} is undefined in every resample")
    return point_c - point_b, _percentile(deltas, 0.025), _percentile(deltas, 0.975)


def cmd_compare(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest))
    base = score_system(manifest, Path(args.baseline))
    cand = score_system(manifest, Path(args.candidate))
    base_blocks = [b for m in manifest.meetings for b in base[m.id]]
    cand_blocks = [b for m in manifest.meetings for b in cand[m.id]]
    if len(base_blocks) != len(cand_blocks):
        raise InputError("baseline and candidate cover different amounts of audio")
    results: dict[str, tuple[float, float, float]] = {}
    for metric in ("der", "id_accuracy", "false_accept"):
        results[metric] = bootstrap_delta(
            base_blocks, cand_blocks, metric, args.bootstrap, args.seed
        )
        point, low, high = results[metric]
        print(
            f"{metric:<13} delta {point * 100:+.2f} pts, 95% interval "
            f"[{low * 100:+.2f}, {high * 100:+.2f}]  ({len(base_blocks)} blocks of 30 s)"
        )
    point, low, high = results[args.require_better]
    better = low > 0 if args.require_better == "id_accuracy" else high < 0
    ok = better
    if not better:
        print(f"FAIL: {args.require_better} is not wholly better (unknown, not 'no effect')")
    if args.require_better != "false_accept":
        high_fa = results["false_accept"][2]
        if high_fa > args.max_false_accept_rise:
            ok = False
            print(
                f"FAIL: wrong names may have risen by up to {high_fa * 100:.2f} pts "
                f"(limit {args.max_false_accept_rise * 100:.2f})"
            )
    print("PASS" if ok else "REJECT")
    return 0 if ok else 1


def _clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def cmd_draft(args: argparse.Namespace) -> int:
    """Turn a system's output into a draft truth file the owner corrects by hand."""
    manifest = load_manifest(Path(args.manifest), need_truth=False)
    hyps = load_hypothesis(Path(args.hypothesis), manifest.meetings)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for meeting in manifest.meetings:
        segs = sorted(hyps[meeting.id], key=lambda s: (s.start, s.end))
        rows = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "speaker": s.speaker} for s in segs
        ]
        (out / f"draft-{meeting.id}.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        lines = [f"[{_clock(s.start)}-{_clock(s.end)}] {s.speaker}" for s in segs]
        (out / f"draft-{meeting.id}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote draft for {meeting.id}: {len(rows)} segments (correct names and edges)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check the manifest, truth and audio files")
    p.add_argument("manifest")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("score", help="DER and naming metrics of one or more systems")
    p.add_argument("manifest")
    p.add_argument("hypotheses", nargs="+")
    p.add_argument("--json")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("compare", help="paired comparison of two systems")
    p.add_argument("manifest")
    p.add_argument("baseline")
    p.add_argument("candidate")
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument(
        "--require-better", choices=("der", "id_accuracy", "false_accept"), default="der"
    )
    p.add_argument("--max-false-accept-rise", type=float, default=0.005)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("draft", help="write a draft truth file from a system's output")
    p.add_argument("manifest")
    p.add_argument("hypothesis")
    p.add_argument("out_dir")
    p.set_defaults(func=cmd_draft)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
