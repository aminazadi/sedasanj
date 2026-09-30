from __future__ import annotations

from worker_llm.chunking import (
    CHARS_PER_TOKEN,
    CHUNK_OVERLAP_TOKENS,
    CHUNK_TOKENS,
    EXTRA_REDUCE_TOKENS,
    SINGLE_PASS_TOKENS,
    estimate_tokens,
    plan_chunks,
)


def _transcript(tokens: int) -> str:
    return "x" * (tokens * CHARS_PER_TOKEN)


def test_short_transcript_is_a_single_pass() -> None:
    plan = plan_chunks(_transcript(200))
    assert plan.strategy == "single"
    assert len(plan.chunks) == 1
    assert plan.extra_reduce is False


def test_long_transcript_is_chunked_and_nothing_is_dropped() -> None:
    text = _transcript(SINGLE_PASS_TOKENS * 3)
    plan = plan_chunks(text)
    assert plan.strategy == "map_reduce"
    assert len(plan.chunks) > 1
    assert all(estimate_tokens(chunk) <= CHUNK_TOKENS for chunk in plan.chunks)
    # Overlapping windows mean the concatenation is longer than the source (§9.2).
    assert len("".join(plan.chunks)) >= len(text)
    assert plan.chunks[0].startswith(text[:100])
    assert text.endswith(plan.chunks[-1][-100:])


def test_chunks_overlap_by_the_configured_window() -> None:
    text = "".join(f"{index:06d}" for index in range(4000))
    plan = plan_chunks(text)
    overlap_chars = CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN
    tail = plan.chunks[0][-overlap_chars:]
    assert plan.chunks[1].startswith(tail)


def test_very_long_transcript_requests_an_extra_reduce_pass() -> None:
    assert plan_chunks(_transcript(EXTRA_REDUCE_TOKENS * 2)).extra_reduce is True
    assert plan_chunks(_transcript(SINGLE_PASS_TOKENS + 10)).extra_reduce is False
