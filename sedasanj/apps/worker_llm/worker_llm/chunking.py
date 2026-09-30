from __future__ import annotations

from dataclasses import dataclass

SINGLE_PASS_TOKENS = 3500
CHUNK_TOKENS = 2500
CHUNK_OVERLAP_TOKENS = 200
EXTRA_REDUCE_TOKENS = 12000
CHARS_PER_TOKEN = 2  # Persian heuristic from §9.2


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


@dataclass(frozen=True)
class ChunkPlan:
    """§9.2 chunking table. Nothing is ever silently truncated."""

    strategy: str
    chunks: list[str]
    extra_reduce: bool


def plan_chunks(text: str) -> ChunkPlan:
    tokens = estimate_tokens(text)
    if tokens < SINGLE_PASS_TOKENS:
        return ChunkPlan(strategy="single", chunks=[text], extra_reduce=False)

    window = CHUNK_TOKENS * CHARS_PER_TOKEN
    overlap = CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN
    step = window - overlap
    chunks = [text[start : start + window] for start in range(0, len(text), step)]
    chunks = [chunk for chunk in chunks if chunk.strip()]
    return ChunkPlan(
        strategy="map_reduce",
        chunks=chunks,
        extra_reduce=tokens > EXTRA_REDUCE_TOKENS,
    )
