from __future__ import annotations

import time
from collections import defaultdict

from redis.asyncio import Redis

from app.config import get_settings
from app.errors import ApiError

_redis: Redis | None = None
_memory: dict[str, list[float]] = defaultdict(list)


def _get_redis() -> Redis | None:
    global _redis
    settings = get_settings()
    if settings.queue_backend == "memory":
        return None
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


async def enforce(bucket: str, limit: int, window_seconds: int = 60) -> None:
    """Fixed-window limiter (§13). Falls back to in-process counters without redis."""
    redis = _get_redis()
    now = time.time()
    if redis is None:
        hits = [t for t in _memory[bucket] if now - t < window_seconds]
        hits.append(now)
        _memory[bucket] = hits
        count = len(hits)
    else:
        key = f"rl:{bucket}:{int(now // window_seconds)}"
        count = int(await redis.incr(key))
        if count == 1:
            await redis.expire(key, window_seconds)
    if count > limit:
        raise ApiError("rate_limited", f"limit of {limit} requests per {window_seconds}s exceeded")
