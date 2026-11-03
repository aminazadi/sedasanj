#!/usr/bin/env python3
"""Score ASR hypotheses against human references (WER / CER) and compare systems.

Standard library only, so it runs anywhere (CI, a laptop without the platform venv).

Golden set layout (see sedasanj/test_data/asr_golden/README.md):
    manifest.json                    {"clips": [{"id", "audio", "reference", "tags": [...]}]}
Hypotheses, one file per system:
    <system>.json                    {"<clip id>": "hypothesis text", ...}

Usage:
    asr_eval.py score MANIFEST HYP.json [HYP2.json ...] [--json OUT]
    asr_eval.py compare MANIFEST BASELINE.json CANDIDATE.json --max-delta 0.02

`compare` exits 1 when the candidate's corpus WER exceeds the baseline's by more than
`--max-delta` (absolute, e.g. 0.02 = 2 percentage points), and 2 on unusable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ClipScore:
    clip_id: str
    ref_words: int
    word_errors: int
    ref_chars: int
    char_errors: int
    tags: tuple[str, ...]

    @property
    def wer(self) -> float:
        return self.word_errors / self.ref_words if self.ref_words else 0.0

    @property
    def cer(self) -> float:
        return self.char_errors / self.ref_chars if self.ref_chars else 0.0


def score_clip(
    clip_id: str, reference: str, hypothesis: str, tags: tuple[str, ...] = ()
) -> ClipScore:
    ref = normalize_for_scoring(reference)
    hyp = normalize_for_scoring(hypothesis)
    ref_words, hyp_words = ref.split(), hyp.split()
    ref_chars, hyp_chars = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    return ClipScore(
        clip_id=clip_id,
        ref_words=len(ref_words),
        word_errors=edit_distance(ref_words, hyp_words),
        ref_chars=len(ref_chars),
        char_errors=edit_distance(ref_chars, hyp_chars),
        tags=tags,
    )


@dataclass(frozen=True)
class Summary:
    clips: int
    ref_words: int
    wer: float
    cer: float
    by_tag: dict[str, float]


def summarize(scores: list[ClipScore]) -> Summary:
    """Corpus-level WER/CER are error-count ratios (not means of per-clip ratios)."""
    words = sum(s.ref_words for s in scores)
    chars = sum(s.ref_chars for s in scores)
    tags: dict[str, list[ClipScore]] = {}
    for score in scores:
        for tag in score.tags:
            tags.setdefault(tag, []).append(score)
    return Summary(
        clips=len(scores),
        ref_words=words,
        wer=sum(s.word_errors for s in scores) / words if words else 0.0,
        cer=sum(s.char_errors for s in scores) / chars if chars else 0.0,
        by_tag={
            tag: (
                sum(s.word_errors for s in group) / sum(s.ref_words for s in group)
                if sum(s.ref_words for s in group)
                else 0.0
            )
            for tag, group in sorted(tags.items())
        },
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
    result: list[dict[str, Any]] = clips
    return result


def load_hypotheses(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalInputError(f"cannot read hypotheses {path}: {exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise EvalInputError(f"hypotheses {path}: expected a JSON object of id -> text")
    return data


def score_system(
    clips: list[dict[str, Any]], hypotheses: dict[str, str], *, name: str
) -> list[ClipScore]:
    """Every manifest clip must have a hypothesis; a missing one would silently flatter WER."""
    missing = [c["id"] for c in clips if c["id"] not in hypotheses]
    if missing:
        raise EvalInputError(
            f"{name}: no hypothesis for {len(missing)} clip(s), e.g. {missing[:3]}; "
            "re-run that system on the whole golden set"
        )
    return [
        score_clip(c["id"], c["reference"], hypotheses[c["id"]], tuple(c.get("tags", ())))
        for c in clips
    ]


def _format(name: str, summary: Summary) -> str:
    lines = [
        f"{name}: clips={summary.clips} words={summary.ref_words} "
        f"WER={summary.wer:.2%} CER={summary.cer:.2%}"
    ]
    lines += [f"    tag {tag}: WER={wer:.2%}" for tag, wer in summary.by_tag.items()]
    return "\n".join(lines)


def _summary_json(summary: Summary) -> dict[str, Any]:
    return {
        "clips": summary.clips,
        "ref_words": summary.ref_words,
        "wer": summary.wer,
        "cer": summary.cer,
        "wer_by_tag": summary.by_tag,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="WER/CER for one or more systems")
    score.add_argument("manifest", type=Path)
    score.add_argument("hypotheses", type=Path, nargs="+")
    score.add_argument("--json", type=Path, help="also write the summaries as JSON")
    compare = sub.add_parser("compare", help="fail when a candidate is worse than a baseline")
    compare.add_argument("manifest", type=Path)
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--max-delta", type=float, default=0.02)
    args = parser.parse_args(argv)

    try:
        clips = load_manifest(args.manifest)
        if args.command == "score":
            report: dict[str, dict[str, Any]] = {}
            for path in args.hypotheses:
                summary = summarize(score_system(clips, load_hypotheses(path), name=path.stem))
                print(_format(path.stem, summary))
                report[path.stem] = _summary_json(summary)
            if args.json:
                args.json.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            return 0
        base = summarize(score_system(clips, load_hypotheses(args.baseline), name="baseline"))
        cand = summarize(score_system(clips, load_hypotheses(args.candidate), name="candidate"))
    except EvalInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_format("baseline", base))
    print(_format("candidate", cand))
    delta = cand.wer - base.wer
    print(f"delta WER (candidate - baseline) = {delta:+.2%}, allowed {args.max_delta:.2%}")
    if delta > args.max_delta:
        print("FAIL: candidate WER regression exceeds the allowed delta", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
