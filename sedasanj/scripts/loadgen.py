"""Fixture load generator for the phase 9 soak (300 h of audio in 24 h).

Generates synthetic stereo PCM WAVs and uploads them through the public ingest
API. It is a capacity harness, not a correctness test.

    uv run python scripts/loadgen.py --base-url https://api.example.com \
        --api-key sk_live_... --calls 6000 --concurrency 16 --seconds 180
"""

from __future__ import annotations

import argparse
import asyncio
import io
import math
import random
import struct
import time
import wave
from datetime import UTC, datetime, timedelta

import httpx


def synth_wav(seconds: int, sample_rate: int = 8000) -> bytes:
    """Two channels of low-amplitude noise+tone: right size, right layout, no content."""
    frames = seconds * sample_rate
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        chunk = bytearray()
        for index in range(frames):
            phase = 2 * math.pi * 220 * index / sample_rate
            left = int(3000 * math.sin(phase)) + random.randint(-200, 200)
            right = int(2500 * math.sin(phase * 1.5)) + random.randint(-200, 200)
            chunk += struct.pack("<hh", left, right)
        handle.writeframes(bytes(chunk))
    return buffer.getvalue()


async def upload(
    client: httpx.AsyncClient, payload: bytes, index: int, seconds: int
) -> tuple[int, float]:
    ended = datetime.now(UTC)
    started = ended - timedelta(seconds=seconds)
    uniqueid = f"load-{int(ended.timestamp())}-{index}"
    began = time.perf_counter()
    response = await client.post(
        "/v1/ingest/calls",
        data={
            "asterisk_uniqueid": uniqueid,
            "caller_number": f"0912{index % 10000000:07d}",
            "dialed_number": "1000",
            "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ended_at": ended.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "direction": "inbound",
        },
        files={"file": (f"{uniqueid}.wav", payload, "audio/wav")},
        headers={"Idempotency-Key": uniqueid},
    )
    return response.status_code, time.perf_counter() - began


async def run(args: argparse.Namespace) -> None:
    payload = synth_wav(args.seconds)
    print(f"fixture: {len(payload) / 1_000_000:.1f} MB, {args.seconds}s stereo")
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    statuses: dict[int, int] = {}

    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=args.timeout,
        headers={"Authorization": f"Bearer {args.api_key}"},
    ) as client:

        async def one(index: int) -> None:
            async with semaphore:
                status, elapsed = await upload(client, payload, index, args.seconds)
                statuses[status] = statuses.get(status, 0) + 1
                latencies.append(elapsed)

        started = time.perf_counter()
        await asyncio.gather(*(one(index) for index in range(args.calls)))
        total = time.perf_counter() - started

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0.0
    print(f"calls={args.calls} wall={total:.1f}s statuses={statuses} ingest_p95={p95:.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="ingest load generator")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--calls", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--timeout", type=float, default=120.0)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
