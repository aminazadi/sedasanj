"""Split long audio at quiet points so one CUDA decode never sees a whole call."""

import numpy as np

DEFAULT_CHUNK_SECONDS = 30.0
SEARCH_SECONDS = 5.0
FRAME_SECONDS = 0.1


def chunk_bounds(samples, sample_rate, max_seconds=DEFAULT_CHUNK_SECONDS):
    """Return (start, end) sample ranges no longer than ``max_seconds``.

    Each cut lands on the quietest 100 ms frame in the last five seconds of the
    window, so words are rarely split. Audio within the limit is one range.
    """
    total = len(samples)
    limit = max(int(sample_rate * max_seconds), 1)
    if total <= limit:
        return [(0, total)]
    frame = max(int(sample_rate * FRAME_SECONDS), 1)
    search = min(int(sample_rate * SEARCH_SECONDS), limit // 2)
    bounds = []
    start = 0
    while total - start > limit:
        end = start + limit
        lo = end - search
        window = np.asarray(samples[lo:end], dtype=np.float64)
        frames = len(window) // frame
        cut = end
        if frames:
            energy = np.square(window[: frames * frame]).reshape(frames, frame).mean(axis=1)
            cut = lo + int(np.argmin(energy)) * frame + frame // 2
        cut = min(max(cut, start + 1), end)
        bounds.append((start, cut))
        start = cut
    bounds.append((start, total))
    return bounds
