#!/usr/bin/env python3
"""Score ASR hypotheses against human references (WER / CER / cpWER) and compare systems.

Standard library only, so it runs anywhere (CI, a laptop without the platform venv).

Golden set layout (see sedasanj/test_data/asr_golden/README.md):
    manifest.json     {"clips": [{"id", "audio", "reference", "tags": [...]}]}
Hypotheses, one file per system:
    <system>.json     {"<clip id>": "hypothesis text", ...}
Optional timing sidecar next to a hypotheses file (same name, `.latency.json` suffix):
    <system>.latency.json
                      {"<clip id>": {"audio_seconds": 61.2, "processing_seconds": 24.0,
                                     "final_latency_seconds": 1.1}, ...}
    `final_latency_seconds` (time from end of speech to final text) is optional.

Speaker-attributed references/hypotheses (for cpWER) are either a list of
`{"speaker": "A", "text": "..."}` segments or a `{"A": "text", ...}` object instead of a string.
A plain-string hypothesis against a speaker-labelled reference is scored as a single stream.

Tags: meeting, phone-8k, quiet, noisy, clean, overlap, numbers, long, codeswitch, lavalier,
table, rev (reverberant), snr-N (SNR in dB), ovl-N (overlap percent), and
non-speech/silence (clips whose reference is empty; every hypothesis word there counts as
hallucination, not WER).

Usage:
    asr_eval.py score MANIFEST HYP.json [HYP2.json ...] [--json OUT]
    asr_eval.py compare MANIFEST BASELINE.json CANDIDATE.json [--max-delta 0.02]
                        [--max-clean-delta 0.0] [--noisy-min-gain 0.0]

`compare` exits 1 when the candidate regresses, and 2 on unusable input. Checks:
overall WER may not rise by more than `--max-delta` (absolute, 0.02 = 2 points); the `clean`
subset may not rise by more than `--max-clean-delta` (default 0: no regression allowed); the
`noisy` subset (WER) and the `overlap` subset (cpWER when speaker-labelled, else WER) must
improve by at least `--noisy-min-gain` relative to the baseline (default 0: must not be worse).
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ZWNJ = "‌"
_DIACRITICS = re.compile(r"[ً-ٰٟـ]")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_for_scoring(text: str) -> str:
    """Scoring-only normalisation, deliberately stricter than the runtime transcript text.

    It removes differences that do not change meaning so WER reflects recognition errors:
    Arabic/Persian letter variants, diacritics, tatweel, ZWNJ vs space, digit script,
    punctuation and case. It is NOT the runtime normalisation (see the parity contract).
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("ۀ", "ه")
    text = _DIACRITICS.sub("", text)
    text = text.replace(ZWNJ, " ").translate(_DIGITS).lower()
    text = _PUNCTUATION.sub(" ", text.replace("_", " "))
    return " ".join(text.split())


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    """Levenshtein distance over tokens (insert/delete/substitute all cost 1)."""
    if not ref:
        return len(hyp)
    previous = list(range(len(hyp) + 1))
    for i, ref_item in enumerate(ref, start=1):
        current = [i] + [0] * len(hyp)
        for j, hyp_item in enumerate(hyp, start=1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ref_item != hyp_item),
            )
        previous = current
    return previous[-1]


def align_counts(ref: list[str], hyp: list[str]) -> tuple[int, int, int]:
    """Minimum-edit alignment split into (substitutions, deletions, insertions).

    Ties prefer a match/substitution, then a deletion, so the split is deterministic. The sum
    always equals `edit_distance`.
    """
    rows, cols = len(ref), len(hyp)
    cost = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows + 1):
        cost[i][0] = i
    for j in range(cols + 1):
        cost[0][j] = j
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            cost[i][j] = min(
                cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]),
                cost[i - 1][j] + 1,
                cost[i][j - 1] + 1,
            )
    subs = dels = ins = 0
    i, j = rows, cols
    while i > 0 or j > 0:
        if i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            subs += ref[i - 1] != hyp[j - 1]
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1:
            dels += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return subs, dels, ins


NON_SPEECH_TAGS = frozenset({"non-speech", "silence"})
KNOWN_TAGS = frozenset(
    {
        "meeting",
        "phone-8k",
        "quiet",
        "noisy",
        "clean",
        "overlap",
        "numbers",
        "long",
        "codeswitch",
        "lavalier",
        "table",
        "rev",
    }
    | NON_SPEECH_TAGS
)
_PARAM_TAG = re.compile(r"^(snr|ovl)-\d+$")
MAX_SPEAKERS = 8  # cpWER tries every speaker permutation; 8! = 40320 assignments is the cap.


def unknown_tags(tags: list[str]) -> list[str]:
    return [t for t in tags if t not in KNOWN_TAGS and not _PARAM_TAG.match(t)]


SpeakerStreams = dict[str, str]


def speaker_streams(value: Any) -> SpeakerStreams | None:
    """Per-speaker text of a speaker-labelled reference/hypothesis; None for a plain string."""
    if isinstance(value, dict):
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise EvalInputError("a speaker object must map speaker name -> text")
        return dict(value)
    if isinstance(value, list):
        streams: SpeakerStreams = {}
        for seg in value:
            if (
                not isinstance(seg, dict)
                or not isinstance(seg.get("speaker"), str)
                or not isinstance(seg.get("text"), str)
            ):
                raise EvalInputError(
                    'speaker segments must look like {"speaker": "A", "text": "..."}'
                )
            streams[seg["speaker"]] = (streams.get(seg["speaker"], "") + " " + seg["text"]).strip()
        return streams
    if isinstance(value, str):
        return None
    raise EvalInputError("a reference/hypothesis must be a string, a segment list or an object")


def flatten_text(value: Any) -> str:
    """Whole text of a plain or speaker-labelled value, in segment order."""
    if isinstance(value, list):
        speaker_streams(value)  # validate shape
        return " ".join(seg["text"] for seg in value)
    streams = speaker_streams(value)
    return value if streams is None else " ".join(streams.values())


def cp_word_errors(ref_streams: SpeakerStreams, hyp_streams: SpeakerStreams) -> tuple[int, int]:
    """cpWER: (errors, reference words) under the best speaker assignment.

    Each speaker's words are concatenated, and hypothesis speakers are matched to reference
    speakers by the permutation with the fewest total word errors (extra speakers on either
    side are matched against an empty stream, so missed or invented speakers are penalised).
    """
    refs = [normalize_for_scoring(t).split() for t in ref_streams.values()]
    hyps = [normalize_for_scoring(t).split() for t in hyp_streams.values()]
    size = max(len(refs), len(hyps))
    if size > MAX_SPEAKERS:
        raise EvalInputError(
            f"cpWER supports at most {MAX_SPEAKERS} speakers per clip, got {size}; "
            "merge minor speakers in the reference"
        )
    refs += [[] for _ in range(size - len(refs))]
    hyps += [[] for _ in range(size - len(hyps))]
    pair = [[edit_distance(r, h) for h in hyps] for r in refs]
    best = min(
        sum(pair[i][j] for i, j in enumerate(perm)) for perm in itertools.permutations(range(size))
    )
    return best, sum(len(r) for r in refs)


@dataclass(frozen=True)
class Timing:
    audio_seconds: float
    processing_seconds: float
    final_latency_seconds: float | None = None

    @property
    def rtf(self) -> float:
        return self.processing_seconds / self.audio_seconds


@dataclass(frozen=True)
class ClipScore:
    clip_id: str
    ref_words: int
    word_errors: int
    ref_chars: int
    char_errors: int
    tags: tuple[str, ...]
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0
    non_speech: bool = False
    cp_ref_words: int | None = None
    cp_errors: int | None = None
    timing: Timing | None = None

    @property
    def wer(self) -> float:
        return self.word_errors / self.ref_words if self.ref_words else 0.0

    @property
    def cer(self) -> float:
        return self.char_errors / self.ref_chars if self.ref_chars else 0.0

    @property
    def hallucinated_words(self) -> int:
        """Words emitted on a clip that has no speech: all of them are insertions."""
        return self.insertions if self.non_speech else 0


def score_clip(
    clip_id: str,
    reference: Any,
    hypothesis: Any,
    tags: tuple[str, ...] = (),
    timing: Timing | None = None,
) -> ClipScore:
    ref = normalize_for_scoring(flatten_text(reference))
    hyp = normalize_for_scoring(flatten_text(hypothesis))
    ref_words, hyp_words = ref.split(), hyp.split()
    ref_chars, hyp_chars = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    subs, dels, ins = align_counts(ref_words, hyp_words)
    cp_errors: int | None = None
    cp_words: int | None = None
    ref_streams = speaker_streams(reference)
    if ref_streams is not None:
        hyp_streams = speaker_streams(hypothesis)
        if hyp_streams is None:
            hyp_streams = {"_": hypothesis}
        cp_errors, cp_words = cp_word_errors(ref_streams, hyp_streams)
    return ClipScore(
        clip_id=clip_id,
        ref_words=len(ref_words),
        word_errors=subs + dels + ins,
        ref_chars=len(ref_chars),
        char_errors=edit_distance(ref_chars, hyp_chars),
        tags=tags,
        substitutions=subs,
        deletions=dels,
        insertions=ins,
        non_speech=bool(NON_SPEECH_TAGS.intersection(tags)),
        cp_ref_words=cp_words,
        cp_errors=cp_errors,
        timing=timing,
    )


def _ratio(errors: int, words: int) -> float:
    return errors / words if words else 0.0


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))]


@dataclass(frozen=True)
class TimingSummary:
    clips: int
    rtf: float  # corpus RTF: total processing time / total audio time
    rtf_p50: float
    rtf_p95: float
    final_latency_mean: float | None
    final_latency_p95: float | None


@dataclass(frozen=True)
class Summary:
    clips: int
    ref_words: int
    wer: float
    cer: float
    by_tag: dict[str, float]
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0
    non_speech_clips: int = 0
    hallucinated_words: int = 0
    hallucinated_clips: int = 0
    cpwer: float | None = None
    cpwer_clips: int = 0
    cpwer_by_tag: dict[str, float] = field(default_factory=dict)
    timing: TimingSummary | None = None


def summarize(scores: list[ClipScore]) -> Summary:
    """Corpus-level WER/CER are error-count ratios (not means of per-clip ratios).

    Clips tagged non-speech/silence are excluded from WER/CER (they have no reference words)
    and reported as hallucination instead.
    """
    speech = [s for s in scores if not s.non_speech]
    silent = [s for s in scores if s.non_speech]
    words = sum(s.ref_words for s in speech)
    chars = sum(s.ref_chars for s in speech)
    tags: dict[str, list[ClipScore]] = {}
    for score in speech:
        for tag in score.tags:
            tags.setdefault(tag, []).append(score)
    cp_scores = [s for s in speech if s.cp_errors is not None and s.cp_ref_words is not None]
    cp_tags: dict[str, list[ClipScore]] = {}
    for score in cp_scores:
        for tag in score.tags:
            cp_tags.setdefault(tag, []).append(score)

    def cp_ratio(group: list[ClipScore]) -> float:
        return _ratio(sum(s.cp_errors or 0 for s in group), sum(s.cp_ref_words or 0 for s in group))

    return Summary(
        clips=len(scores),
        ref_words=words,
        wer=_ratio(sum(s.word_errors for s in speech), words),
        cer=_ratio(sum(s.char_errors for s in speech), chars),
        by_tag={
            tag: _ratio(sum(s.word_errors for s in group), sum(s.ref_words for s in group))
            for tag, group in sorted(tags.items())
        },
        substitutions=sum(s.substitutions for s in speech),
        deletions=sum(s.deletions for s in speech),
        insertions=sum(s.insertions for s in speech),
        non_speech_clips=len(silent),
        hallucinated_words=sum(s.hallucinated_words for s in silent),
        hallucinated_clips=sum(1 for s in silent if s.hallucinated_words),
        cpwer=cp_ratio(cp_scores) if cp_scores else None,
        cpwer_clips=len(cp_scores),
        cpwer_by_tag={tag: cp_ratio(group) for tag, group in sorted(cp_tags.items())},
        timing=_summarize_timing(scores),
    )


def _summarize_timing(scores: list[ClipScore]) -> TimingSummary | None:
    timed = [s.timing for s in scores if s.timing is not None]
    if not timed:
        return None
    rtfs = [t.rtf for t in timed]
    latencies = [t.final_latency_seconds for t in timed if t.final_latency_seconds is not None]
    return TimingSummary(
        clips=len(timed),
        rtf=sum(t.processing_seconds for t in timed) / sum(t.audio_seconds for t in timed),
        rtf_p50=_percentile(rtfs, 0.5),
        rtf_p95=_percentile(rtfs, 0.95),
        final_latency_mean=sum(latencies) / len(latencies) if latencies else None,
        final_latency_p95=_percentile(latencies, 0.95) if latencies else None,
    )


class EvalInputError(ValueError):
    """Unusable manifest or hypothesis file. The message names the fix."""


def load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        clips = data["clips"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise EvalInputError(
            f"cannot read manifest {path}: expected JSON with a 'clips' list ({exc})"
        ) from exc
    seen: set[str] = set()
    for clip in clips:
        clip_id = clip.get("id")
        if not clip_id or "reference" not in clip:
            raise EvalInputError(f"manifest {path}: every clip needs 'id' and 'reference'")
        if clip_id in seen:
            raise EvalInputError(f"manifest {path}: duplicate clip id {clip_id!r}")
        seen.add(clip_id)
        try:
            speaker_streams(clip["reference"])
        except EvalInputError as exc:
            raise EvalInputError(f"manifest {path}: clip {clip_id!r}: {exc}") from exc
        odd = unknown_tags(list(clip.get("tags", ())))
        if odd:
            print(
                f"warning: clip {clip_id!r} has unknown tag(s) {odd}; "
                "known tags are listed in the asr_eval.py docstring",
                file=sys.stderr,
            )
    result: list[dict[str, Any]] = clips
    return result


def load_hypotheses(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalInputError(f"cannot read hypotheses {path}: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        raise EvalInputError(f"hypotheses {path}: expected a JSON object of id -> text")
    for clip_id, value in data.items():
        try:
            speaker_streams(value)
        except EvalInputError as exc:
            raise EvalInputError(f"hypotheses {path}: clip {clip_id!r}: {exc}") from exc
    return data


def timing_sidecar(hypotheses_path: Path) -> Path:
    return hypotheses_path.with_name(hypotheses_path.stem + ".latency.json")


def load_timing(path: Path) -> dict[str, Timing]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, Timing] = {}
        for clip_id, row in data.items():
            audio = float(row["audio_seconds"])
            processing = float(row["processing_seconds"])
            final = row.get("final_latency_seconds")
            if audio <= 0 or processing < 0 or (final is not None and float(final) < 0):
                raise ValueError(f"{clip_id}: audio_seconds must be > 0 and times >= 0")
            result[clip_id] = Timing(audio, processing, None if final is None else float(final))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise EvalInputError(
            f"cannot read timing sidecar {path}: expected an object of clip id -> "
            f"{{audio_seconds, processing_seconds[, final_latency_seconds]}} ({exc})"
        ) from exc
    return result


def score_system(
    clips: list[dict[str, Any]],
    hypotheses: dict[str, Any],
    *,
    name: str,
    timings: dict[str, Timing] | None = None,
) -> list[ClipScore]:
    """Every manifest clip must have a hypothesis; a missing one would silently flatter WER."""
    missing = [c["id"] for c in clips if c["id"] not in hypotheses]
    if missing:
        raise EvalInputError(
            f"{name}: no hypothesis for {len(missing)} clip(s), e.g. {missing[:3]}; "
            "re-run that system on the whole golden set"
        )
    if timings is not None:
        untimed = [c["id"] for c in clips if c["id"] not in timings]
        if untimed:
            raise EvalInputError(
                f"{name}: timing sidecar lacks {len(untimed)} clip(s), e.g. {untimed[:3]}; "
                "re-run the timing capture on the whole golden set or delete the sidecar"
            )
    try:
        return [
            score_clip(
                c["id"],
                c["reference"],
                hypotheses[c["id"]],
                tuple(c.get("tags", ())),
                timings[c["id"]] if timings is not None else None,
            )
            for c in clips
        ]
    except EvalInputError as exc:
        raise EvalInputError(f"{name}: {exc}") from exc


def score_path(clips: list[dict[str, Any]], path: Path, *, name: str) -> Summary:
    sidecar = timing_sidecar(path)
    timings = load_timing(sidecar) if sidecar.is_file() else None
    return summarize(score_system(clips, load_hypotheses(path), name=name, timings=timings))


def _format(name: str, summary: Summary) -> str:
    lines = [
        f"{name}: clips={summary.clips} words={summary.ref_words} "
        f"WER={summary.wer:.2%} CER={summary.cer:.2%}",
        f"    errors: substitutions={summary.substitutions} "
        f"deletions={summary.deletions} insertions={summary.insertions}",
    ]
    if summary.non_speech_clips:
        lines.append(
            f"    hallucination: {summary.hallucinated_words} word(s) in "
            f"{summary.hallucinated_clips}/{summary.non_speech_clips} non-speech clip(s)"
        )
    if summary.cpwer is not None:
        lines.append(f"    cpWER={summary.cpwer:.2%} over {summary.cpwer_clips} speaker clip(s)")
        lines += [f"    tag {t}: cpWER={v:.2%}" for t, v in summary.cpwer_by_tag.items()]
    if summary.timing is not None:
        t = summary.timing
        line = f"    timing: RTF={t.rtf:.3f} p50={t.rtf_p50:.3f} p95={t.rtf_p95:.3f}"
        if t.final_latency_mean is not None and t.final_latency_p95 is not None:
            line += (
                f" final-latency mean={t.final_latency_mean:.2f}s p95={t.final_latency_p95:.2f}s"
            )
        lines.append(line)
    lines += [f"    tag {tag}: WER={wer:.2%}" for tag, wer in summary.by_tag.items()]
    return "\n".join(lines)


def _summary_json(summary: Summary) -> dict[str, Any]:
    report: dict[str, Any] = {
        "clips": summary.clips,
        "ref_words": summary.ref_words,
        "wer": summary.wer,
        "cer": summary.cer,
        "wer_by_tag": summary.by_tag,
        "substitutions": summary.substitutions,
        "deletions": summary.deletions,
        "insertions": summary.insertions,
        "non_speech_clips": summary.non_speech_clips,
        "hallucinated_words": summary.hallucinated_words,
        "hallucinated_clips": summary.hallucinated_clips,
        "cpwer": summary.cpwer,
        "cpwer_clips": summary.cpwer_clips,
        "cpwer_by_tag": summary.cpwer_by_tag,
    }
    t = summary.timing
    report["timing"] = (
        None
        if t is None
        else {
            "clips": t.clips,
            "rtf": t.rtf,
            "rtf_p50": t.rtf_p50,
            "rtf_p95": t.rtf_p95,
            "final_latency_mean": t.final_latency_mean,
            "final_latency_p95": t.final_latency_p95,
        }
    )
    return report


_EPS = 1e-12


def compare_summaries(
    base: Summary,
    cand: Summary,
    *,
    max_delta: float,
    max_clean_delta: float,
    noisy_min_gain: float,
) -> list[str]:
    """Return one failure message per violated gate (empty list = candidate passes)."""
    failures: list[str] = []
    delta = cand.wer - base.wer
    if delta > max_delta + _EPS:
        failures.append(
            f"overall WER rose {delta:+.2%}, allowed {max_delta:.2%}; "
            "inspect the per-tag lines to find the regressing subset"
        )
    if "clean" in base.by_tag and "clean" in cand.by_tag:
        clean = cand.by_tag["clean"] - base.by_tag["clean"]
        if clean > max_clean_delta + _EPS:
            failures.append(
                f"clean WER rose {clean:+.2%}, allowed {max_clean_delta:.2%}; "
                "a clean-audio regression blocks the change"
            )
    for tag in ("noisy", "overlap"):
        base_value, cand_value, metric = _gate_value(base, tag), _gate_value(cand, tag), "WER"
        if base_value is None or cand_value is None:
            continue
        if tag == "overlap" and tag in base.cpwer_by_tag and tag in cand.cpwer_by_tag:
            metric = "cpWER"
        limit = base_value * (1 - noisy_min_gain)
        if cand_value > limit + _EPS:
            failures.append(
                f"{tag} {metric} {cand_value:.2%} is not at least {noisy_min_gain:.0%} better "
                f"than baseline {base_value:.2%}"
            )
    return failures


def _gate_value(summary: Summary, tag: str) -> float | None:
    if tag == "overlap" and tag in summary.cpwer_by_tag:
        return summary.cpwer_by_tag[tag]
    return summary.by_tag.get(tag)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="WER/CER/cpWER and timing for one or more systems")
    score.add_argument("manifest", type=Path)
    score.add_argument("hypotheses", type=Path, nargs="+")
    score.add_argument("--json", type=Path, help="also write the summaries as JSON")
    compare = sub.add_parser("compare", help="fail when a candidate is worse than a baseline")
    compare.add_argument("manifest", type=Path)
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--max-delta", type=float, default=0.02, help="overall WER, absolute")
    compare.add_argument(
        "--max-clean-delta", type=float, default=0.0, help="clean-tag WER, absolute (0 = none)"
    )
    compare.add_argument(
        "--noisy-min-gain",
        type=float,
        default=0.0,
        help="required relative improvement on noisy (WER) and overlap (cpWER) tags",
    )
    args = parser.parse_args(argv)

    try:
        clips = load_manifest(args.manifest)
        if args.command == "score":
            report: dict[str, dict[str, Any]] = {}
            for path in args.hypotheses:
                summary = score_path(clips, path, name=path.stem)
                print(_format(path.stem, summary))
                report[path.stem] = _summary_json(summary)
            if args.json:
                args.json.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            return 0
        base = score_path(clips, args.baseline, name="baseline")
        cand = score_path(clips, args.candidate, name="candidate")
    except EvalInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_format("baseline", base))
    print(_format("candidate", cand))
    print(f"delta WER (candidate - baseline) = {cand.wer - base.wer:+.2%}")
    failures = compare_summaries(
        base,
        cand,
        max_delta=args.max_delta,
        max_clean_delta=args.max_clean_delta,
        noisy_min_gain=args.noisy_min_gain,
    )
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
