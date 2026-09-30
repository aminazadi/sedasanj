#!/usr/bin/env python3

import gzip
import hashlib
import os
import shutil
import subprocess
import tempfile
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

BASE_URL = "https://app.voicesanj.ir"
AUDIO_DIR = Path.home() / "Downloads" / "hamcall_audios"


def rfc3339(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as recording:
        return recording.getnframes() / recording.getframerate()


def unique_id(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    return f"hamcall-{digest}"


def archive(path: Path) -> Path:
    target = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as source, target.open("wb") as raw:
        with gzip.GzipFile(filename=path.name, mode="wb", fileobj=raw) as output:
            shutil.copyfileobj(source, output)
    return target


def normalized_wav(path: Path, directory: Path) -> Path:
    if path.read_bytes()[:4] == b"RIFF":
        return path
    target = directory / path.name
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-ar",
            "8000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target


def main():
    api_key = os.environ.get("CBI_API_KEY")
    if not api_key:
        raise SystemExit("CBI_API_KEY is required")

    files = sorted(AUDIO_DIR.glob("*.wav"))
    if not files:
        raise SystemExit("No WAV files found")

    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=60) as client:
        health = client.get("/v1/ingest/health")
        health.raise_for_status()

        ended = datetime.now(UTC)
        with tempfile.TemporaryDirectory() as temporary:
            temporary_directory = Path(temporary)
            for path in files:
                source_path = normalized_wav(path, temporary_directory)
                duration = duration_seconds(source_path)
                started = ended - timedelta(seconds=duration)
                archive_path = archive(source_path)
                call_id = unique_id(path)
                try:
                    with archive_path.open("rb") as handle:
                        response = client.post(
                            "/v1/ingest/calls",
                            headers={"Idempotency-Key": call_id},
                            data={
                                "asterisk_uniqueid": call_id,
                                "caller_number": "unknown",
                                "dialed_number": "unknown",
                                "started_at": rfc3339(started),
                                "ended_at": rfc3339(ended),
                            },
                            files={"file": (path.name + ".gz", handle, "application/gzip")},
                        )
                    response.raise_for_status()
                except Exception:
                    archive_path.unlink(missing_ok=True)
                    raise

                print(f"Uploaded: {path.name} ({response.json().get('call_id', 'accepted')})")
                path.unlink()
                archive_path.unlink(missing_ok=True)
                ended = started - timedelta(seconds=1)


if __name__ == "__main__":
    main()
