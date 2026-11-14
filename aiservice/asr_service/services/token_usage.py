"""Exact token accounting: only what the upstream model reported, never an estimate."""

SOURCE_REPORTED = "reported"
SOURCE_UNAVAILABLE = "unavailable"


def _count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value >= 0 else None


def normalize_usage(raw, origin):
    """Return OpenAI-style counts plus where they came from.

    ``raw`` is the ``usage`` object of a local llama.cpp result or a 9Router response. Both the
    ``prompt/completion`` and the ``input/output`` spellings are accepted. When the upstream did
    not report both sides the counts stay ``None`` and ``source`` is ``unavailable`` — a missing
    value is never turned into zero.
    """
    prompt = completion = total = None
    if isinstance(raw, dict):
        prompt = _count(raw.get("prompt_tokens", raw.get("input_tokens")))
        completion = _count(raw.get("completion_tokens", raw.get("output_tokens")))
        total = _count(raw.get("total_tokens"))
    if prompt is None or completion is None:
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "source": SOURCE_UNAVAILABLE,
            "origin": origin,
        }
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total if total is not None else prompt + completion,
        "source": SOURCE_REPORTED,
        "origin": origin,
    }
