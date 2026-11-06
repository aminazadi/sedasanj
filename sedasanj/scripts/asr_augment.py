#!/usr/bin/env python3
"""Build controlled noisy / reverberant / overlapped ASR benchmark clips from clean ones.

Input is an `asr_eval.py` manifest whose clips point at clean 16 kHz mono WAV files. Output is a
directory of mixtures plus a new manifest that `asr_eval.py` scores directly:

    <out>/manifest.json
    <out>/audio/<clip id>__snr10.wav | __rev.wav | __ovl20.wav

Variants (all deterministic for a given --seed; the random stream of each variant depends only
on seed + clip id + variant, not on processing order):
    snr-N   additive noise at N dB SNR (default 20, 10, 5, 0). Tags: snr-N, plus `noisy` when
            N <= 10. `clean` is dropped because the clip is no longer clean.
    rev     convolution with a synthetic exponentially decaying room impulse response
            (random RT60 in 0.3-0.8 s). Tags: `rev`; `clean` is dropped.
    ovl-N   the clip overlapped with the next clip in the manifest (a different speaker is
            assumed) so that N percent of the first clip is covered (default 0, 10, 20, 40).
            The reference becomes speaker-labelled ("A": this clip, "B": the other) so that
            `asr_eval.py` reports cpWER. Tags: ovl-N, plus `overlap` when N > 0.
    quiet-N the clip with its level lowered by N dB and nothing else changed (default 20, 30),
            the far or soft-spoken talker. It shows whether words disappear before the
            recognizer sees them (the VAD threshold, level normalisation). Tags: quiet-N,
            plus `quiet`. `clean` is dropped because the clip is not at its recorded level.
    noise-only
            one clip with no speech at all: the noise alone, as loud as it is in the snr-S
            variants (default 30 s at S = 5). Every word a system emits there is invented,
            so `asr_eval.py` reports it as hallucination. Tags: non-speech, noise-only.

Noise comes from --noise (your own recording or a freely licensed set; confirm the licence
before using one). Without it a synthetic pink noise is used, which is licence-free but
easier than real babble or street noise, so it is only a smoke-level condition: pink noise
rarely resembles speech, so a zero in the noise-only clip proves little until it is a real
recording of the room.

Requires numpy and soundfile (optional dependencies, not part of the platform image):
    pip install numpy soundfile

Never commit the generated audio or manifest: they can contain customer speech (`*.wav` is
gitignored; keep OUT_DIR outside the repo or under a gitignored path). Usage:
    asr_augment.py MANIFEST OUT_DIR [--audio-root DIR] [--noise NOISE.wav] [--seed 1234]
                   [--snr 20 10 5 0] [--overlap 0 10 20 40] [--no-rev] [--quiet 20 30]
                   [--noise-only SECONDS] [--noise-only-snr 5] [--keep-originals]

--keep-originals copies the input clips into OUT_DIR unchanged (same id, reference and tags) so
the output manifest holds the clean set and its variants together.
"""

from __future__ import annotations

import argparse
import json
import sys
import zlib
from pathlib import Path
from typing import Any

try:
    import numpy as np
    import soundfile as sf
except ImportError:  # pragma: no cover - exercised only without the optional dependencies
    np = None  # type: ignore[assignment]
    sf = None  # type: ignore[assignment]

SAMPLE_RATE = 16_000
NON_SPEECH_TAGS = {"non-speech", "silence"}
DEFAULT_SNRS = (20, 10, 5, 0)
DEFAULT_OVERLAPS = (0, 10, 20, 40)
DEFAULT_QUIET_DB = (20, 30)
DEFAULT_NOISE_ONLY_SECONDS = 30.0
DEFAULT_NOISE_ONLY_SNR = 5
NOISE_ONLY_ID = "noise-only"
_PEAK = 0.99


class AugmentError(ValueError):
    """Unusable input. The message names the fix."""


def require_audio_deps() -> None:
    if np is None or sf is None:
        raise AugmentError("numpy and soundfile are required: pip install numpy soundfile")


def variant_rng(seed: int, clip_id: str, variant: str) -> Any:
    """Independent, order-free random stream per (seed, clip, variant)."""
    return np.random.default_rng(zlib.crc32(f"{seed}:{clip_id}:{variant}".encode()))


def read_clip(path: Path) -> Any:
    """Load a mono 16 kHz WAV as float64 in [-1, 1]."""
    try:
        data, rate = sf.read(str(path), dtype="float64", always_2d=True)
    except (OSError, RuntimeError) as exc:
        raise AugmentError(f"cannot read audio {path}: {exc}") from exc
    if rate != SAMPLE_RATE or data.shape[1] != 1:
        raise AugmentError(
            f"{path}: need {SAMPLE_RATE} Hz mono, got {rate} Hz with {data.shape[1]} channel(s); "
            f"convert with: ffmpeg -i IN -ar {SAMPLE_RATE} -ac 1 OUT.wav"
        )
    return data[:, 0]


def write_clip(path: Path, samples: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(samples, -1.0, 1.0), SAMPLE_RATE, subtype="PCM_16")


def rms(samples: Any) -> float:
    return float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0


def _limit_peak(samples: Any) -> Any:
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    return samples * (_PEAK / peak) if peak > _PEAK else samples


def pink_noise(length: int, rng: Any) -> Any:
    """Synthetic 1/f noise (power ~ 1/f), unit RMS."""
    spectrum = np.fft.rfft(rng.standard_normal(length))
    freqs = np.arange(len(spectrum), dtype="float64")
    freqs[0] = 1.0
    shaped = np.fft.irfft(spectrum / np.sqrt(freqs), n=length)
    return shaped / rms(shaped)


def fit_noise(noise: Any, length: int, rng: Any) -> Any:
    """Loop a noise recording to `length`, starting at a random offset."""
    if len(noise) == 0:
        raise AugmentError("the noise file is empty; pass a recording with audible noise")
    start = int(rng.integers(0, len(noise)))
    return np.resize(np.roll(noise, -start), length)


def _noise_gain(speech_rms: float, noise_rms: float, snr_db: float) -> float:
    """The factor that makes speech-RMS / noise-RMS equal `snr_db`."""
    if speech_rms == 0.0:
        raise AugmentError("cannot mix at a target SNR into a silent clip; drop it from the set")
    if noise_rms == 0.0:
        raise AugmentError("the noise has zero energy; pass a recording with audible noise")
    return speech_rms / (noise_rms * 10 ** (snr_db / 20))


def mix_at_snr(speech: Any, noise: Any, snr_db: float) -> Any:
    """Scale `noise` so speech-RMS / noise-RMS equals `snr_db`, add, and avoid clipping."""
    gain = _noise_gain(rms(speech), rms(noise), snr_db)
    return _limit_peak(speech + gain * noise)


def noise_only_track(noise: Any, speech_rms: float, snr_db: float) -> Any:
    """The noise alone, as loud as it is in a mixture at `snr_db` against speech of `speech_rms`."""
    return _limit_peak(_noise_gain(speech_rms, rms(noise), snr_db) * noise)


def attenuate(speech: Any, db: float) -> Any:
    """Lower the level by `db` decibels. Only the gain changes: no noise and no limiter."""
    if db < 0:
        raise AugmentError(f"the quiet attenuation must be 0 dB or more, got {db}")
    return speech * 10 ** (-db / 20)


def synthetic_rir(rng: Any) -> Any:
    """Exponentially decaying noise tail with a unit direct path; RT60 drawn in 0.3-0.8 s."""
    rt60 = float(rng.uniform(0.3, 0.8))
    length = int(rt60 * SAMPLE_RATE)
    t = np.arange(length) / SAMPLE_RATE
    tail = rng.standard_normal(length) * np.exp(-6.9078 * t / rt60)  # 60 dB drop at rt60
    tail[: int(0.004 * SAMPLE_RATE)] = 0.0  # direct sound arrives alone, early reflections after
    tail *= 0.25 / max(rms(tail), 1e-12)
    rir = tail
    rir[0] = 1.0
    return rir


def reverberate(speech: Any, rir: Any) -> Any:
    """FFT-convolve with the RIR, trim to the input length and restore the original RMS."""
    size = 1 << (len(speech) + len(rir) - 1).bit_length()
    wet = np.fft.irfft(np.fft.rfft(speech, size) * np.fft.rfft(rir, size), size)[: len(speech)]
    wet_rms = rms(wet)
    if wet_rms == 0.0:
        return wet
    return _limit_peak(wet * (rms(speech) / wet_rms))


def overlap_mix(first: Any, second: Any, percent: int) -> Any:
    """Overlay `second` so that `percent` of `first`'s duration is covered by it.

    The overlapped span is capped at the length of `second`. 0 percent places the clips
    back to back. `second` is scaled to the same RMS as `first` (0 dB speaker ratio).
    """
    if not 0 <= percent <= 100:
        raise AugmentError(f"overlap percent must be 0-100, got {percent}")
    overlap = min(int(round(len(first) * percent / 100)), len(second))
    gain = rms(first) / rms(second) if rms(second) else 1.0
    start = len(first) - overlap
    mixed = np.zeros(start + len(second))
    mixed[: len(first)] += first
    mixed[start:] += gain * second
    return _limit_peak(mixed)


def _derived_tags(tags: list[str], extra: list[str]) -> list[str]:
    kept = [t for t in tags if t not in {"clean", "noisy", "overlap", "quiet"}]
    return kept + [t for t in extra if t not in kept]


def augment_manifest(
    clips: list[dict[str, Any]],
    audio_root: Path,
    out_dir: Path,
    *,
    seed: int,
    snrs: tuple[int, ...] = DEFAULT_SNRS,
    overlaps: tuple[int, ...] = DEFAULT_OVERLAPS,
    reverb: bool = True,
    noise: Any = None,
    quiet: tuple[int, ...] = DEFAULT_QUIET_DB,
    noise_only_seconds: float = DEFAULT_NOISE_ONLY_SECONDS,
    noise_only_snr: int = DEFAULT_NOISE_ONLY_SNR,
    keep_originals: bool = False,
) -> list[dict[str, Any]]:
    """Write all mixtures under `out_dir/audio` and return the new manifest clips.

    With `keep_originals` every input clip is copied first, unchanged (same id, reference and
    tags), so one manifest holds the clean set and its variants and `asr_eval.py compare` can
    gate the `clean` subset against the noisy ones in a single run.
    """
    require_audio_deps()
    if noise_only_seconds < 0:
        raise AugmentError("the noise-only length must be 0 (skip it) or more seconds")
    usable = [
        c
        for c in clips
        if not NON_SPEECH_TAGS.intersection(c.get("tags", ())) and isinstance(c["reference"], str)
    ]
    if not usable:
        raise AugmentError(
            "no usable clip: augmentation needs speech clips with a plain-text reference"
        )
    if overlaps and len(usable) < 2:
        raise AugmentError("overlap mixtures need at least 2 clips; pass --overlap with no values")
    produced: list[dict[str, Any]] = []
    levels: list[float] = []

    def emit(name: str, samples: Any, reference: Any, tags: list[str]) -> None:
        if any(c["id"] == name for c in produced):
            raise AugmentError(f"two clips would be called {name!r}; rename the input clip")
        write_clip(out_dir / "audio" / f"{name}.wav", samples)
        produced.append(
            {"id": name, "audio": f"audio/{name}.wav", "reference": reference, "tags": tags}
        )

    def noise_track_for(length: int, rng: Any) -> Any:
        return pink_noise(length, rng) if noise is None else fit_noise(noise, length, rng)

    if keep_originals:
        for clip in clips:
            emit(
                clip["id"],
                read_clip(audio_root / clip["audio"]),
                clip["reference"],
                list(clip.get("tags", ())),
            )
    for index, clip in enumerate(usable):
        clip_id, tags = clip["id"], list(clip.get("tags", ()))
        speech = read_clip(audio_root / clip["audio"])
        levels.append(rms(speech))
        for snr in snrs:
            noise_track = noise_track_for(len(speech), variant_rng(seed, clip_id, f"snr{snr}"))
            extra = [f"snr-{snr}"] + (["noisy"] if snr <= 10 else [])
            emit(
                f"{clip_id}__snr{snr}",
                mix_at_snr(speech, noise_track, snr),
                clip["reference"],
                _derived_tags(tags, extra),
            )
        if reverb:
            rir = synthetic_rir(variant_rng(seed, clip_id, "rev"))
            emit(
                f"{clip_id}__rev",
                reverberate(speech, rir),
                clip["reference"],
                _derived_tags(tags, ["rev"]),
            )
        for db in quiet:
            emit(
                f"{clip_id}__q{db}",
                attenuate(speech, db),
                clip["reference"],
                _derived_tags(tags, [f"quiet-{db}", "quiet"]),
            )
        if overlaps:
            other = usable[(index + 1) % len(usable)]
            second = read_clip(audio_root / other["audio"])
            for pct in overlaps:
                reference = [
                    {"speaker": "A", "text": clip["reference"]},
                    {"speaker": "B", "text": other["reference"]},
                ]
                emit(
                    f"{clip_id}__ovl{pct}",
                    overlap_mix(speech, second, pct),
                    reference,
                    _derived_tags(tags, [f"ovl-{pct}"] + (["overlap"] if pct > 0 else [])),
                )
    if noise_only_seconds > 0:
        track = noise_track_for(
            int(round(noise_only_seconds * SAMPLE_RATE)),
            variant_rng(seed, NOISE_ONLY_ID, "noise"),
        )
        emit(
            NOISE_ONLY_ID,
            noise_only_track(track, sum(levels) / len(levels), noise_only_snr),
            "",
            ["non-speech", NOISE_ONLY_ID],
        )
    return produced


def write_manifest(out_dir: Path, clips: list[dict[str, Any]]) -> Path:
    """Atomically write the manifest (temp file in the same directory, then rename)."""
    target = out_dir / "manifest.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps({"clips": clips}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifest", type=Path, help="asr_eval.py manifest of clean clips")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--audio-root", type=Path, help="default: the manifest's directory")
    parser.add_argument("--noise", type=Path, help="noise WAV (16 kHz mono); default pink noise")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--snr", type=int, nargs="*", default=list(DEFAULT_SNRS))
    parser.add_argument("--overlap", type=int, nargs="*", default=list(DEFAULT_OVERLAPS))
    parser.add_argument("--no-rev", action="store_true", help="skip the reverberant variant")
    parser.add_argument(
        "--quiet",
        type=int,
        nargs="*",
        default=list(DEFAULT_QUIET_DB),
        metavar="DB",
        help="quieter copies, level lowered by DB decibels (no values: skip them)",
    )
    parser.add_argument(
        "--noise-only",
        type=float,
        default=DEFAULT_NOISE_ONLY_SECONDS,
        metavar="SECONDS",
        help="length of the no-speech noise clip that counts hallucinated words (0: skip it)",
    )
    parser.add_argument(
        "--noise-only-snr",
        type=int,
        default=DEFAULT_NOISE_ONLY_SNR,
        metavar="DB",
        help="the noise-only clip is as loud as the noise in the snr-DB variants",
    )
    parser.add_argument(
        "--keep-originals",
        action="store_true",
        help="copy every input clip into the output unchanged, ahead of its variants",
    )
    args = parser.parse_args(argv)
    try:
        require_audio_deps()
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        clips = data["clips"]
        noise = read_clip(args.noise) if args.noise else None
        produced = augment_manifest(
            clips,
            args.audio_root or args.manifest.parent,
            args.out_dir,
            seed=args.seed,
            snrs=tuple(args.snr),
            overlaps=tuple(args.overlap),
            reverb=not args.no_rev,
            noise=noise,
            quiet=tuple(args.quiet),
            noise_only_seconds=args.noise_only,
            noise_only_snr=args.noise_only_snr,
            keep_originals=args.keep_originals,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:  # AugmentError is a ValueError
        print(f"error: {exc}", file=sys.stderr)
        return 2
    path = write_manifest(args.out_dir, produced)
    print(f"wrote {len(produced)} clip(s) and {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
