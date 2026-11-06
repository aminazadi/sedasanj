#!/usr/bin/env python3
"""Measure candidate gzip settings using read-only representative backup inputs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

BLOCK = 1024 * 1024


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def measure(
    source: Path, target: Path, codec: str, runs: int, window_seconds: float
) -> dict[str, Any]:
    durations = []
    expected = _sha256(source)
    for _ in range(runs):
        started = time.monotonic()
        with source.open("rb") as raw, target.open("wb") as output:
            if codec == "gzip-9":
                with gzip.GzipFile(
                    filename="", fileobj=output, mode="wb", compresslevel=9, mtime=0
                ) as compressed:
                    shutil.copyfileobj(raw, compressed, BLOCK)
            else:
                subprocess.run(
                    ["pigz", "-11", "-n", "-c", "-p", "1"],
                    stdin=raw,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=window_seconds,
                )
        durations.append(time.monotonic() - started)
        with gzip.open(target, "rb") as result:
            if hashlib.file_digest(result, "sha256").hexdigest() != expected:
                raise ValueError("gzip round trip changed the source")
    # Nearest-rank p95 for small samples is the slowest observed run.
    return {
        "compressed_bytes": target.stat().st_size,
        "p50_seconds": round(statistics.median(durations), 3),
        "p95_seconds": round(max(durations), 3),
        "round_trip_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for label in ("small", "medium", "large"):
        parser.add_argument(f"--{label}", type=Path, required=True)
    parser.add_argument("--window-seconds", type=float, required=True)
    parser.add_argument("--runs", type=int, choices=range(3, 11), default=3)
    parser.add_argument("--compare-pigz", action="store_true")
    args = parser.parse_args()
    if args.window_seconds <= 0 or (args.compare_pigz and not shutil.which("pigz")):
        parser.error("provide a positive backup window and install pigz for comparison")
    report = {}
    try:
        with tempfile.TemporaryDirectory(prefix="sedasanj-gzip-benchmark-") as scratch:
            artifact = Path(scratch) / "sample.gzip"
            for cohort in ("small", "medium", "large"):
                source = getattr(args, cohort)
                if not source.is_file() or not source.stat().st_size:
                    parser.error("choose a nonempty regular input for each cohort")
                baseline = measure(source, artifact, "gzip-9", args.runs, args.window_seconds)
                item = {
                    "input_bytes": source.stat().st_size,
                    "gzip_9": baseline,
                    "recommended_codec": "gzip-9",
                }
                if args.compare_pigz:
                    try:
                        candidate = measure(
                            source, artifact, "pigz-11", args.runs, args.window_seconds
                        )
                        item["pigz_11"] = candidate
                        if (
                            candidate["compressed_bytes"] <= baseline["compressed_bytes"] * 0.95
                            and candidate["p95_seconds"] <= args.window_seconds * 0.8
                        ):
                            item["recommended_codec"] = "pigz-11"
                    except subprocess.TimeoutExpired:
                        item["pigz_11"] = {"status": "outside_backup_window"}
                report[cohort] = item
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Compression benchmark failed: {type(exc).__name__}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
