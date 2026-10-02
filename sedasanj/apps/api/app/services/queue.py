from __future__ import annotations

import abc
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings

QUEUE_ASR = "q:asr"
QUEUE_EMOTION = "q:emotion"
QUEUE_LLM = "q:llm"
QUEUE_NOTIFY = "q:notify"

JOB_ASR = "transcribe_call"
JOB_EMOTION = "analyze_voice_sentiment"
JOB_LLM = "analyze_call"
JOB_CORRECTION = "start_transcript_correction"
JOB_NOTIFY = "deliver_event"


class Queue(abc.ABC):
    @abc.abstractmethod
    async def enqueue(
        self,
        queue: str,
        function: str,
        payload: dict[str, Any],
        *,
        defer: timedelta | None = None,
        job_id: str | None = None,
    ) -> None: ...

    @abc.abstractmethod
    async def depth(self, queue: str) -> int: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


class RedisQueue(Queue):
    def __init__(self) -> None:
        self._pools: dict[str, ArqRedis] = {}

    async def _pool(self, queue: str) -> ArqRedis:
        if queue not in self._pools:
            settings = get_settings()
            self._pools[queue] = await create_pool(
                RedisSettings.from_dsn(settings.redis_url), default_queue_name=queue
            )
        return self._pools[queue]

    async def enqueue(
        self,
        queue: str,
        function: str,
        payload: dict[str, Any],
        *,
        defer: timedelta | None = None,
        job_id: str | None = None,
    ) -> None:
        pool = await self._pool(queue)
        await pool.enqueue_job(function, payload, _defer_by=defer, _job_id=job_id)

    async def depth(self, queue: str) -> int:
        pool = await self._pool(queue)
        return int(await pool.zcard(queue))

    async def close(self) -> None:
        for pool in self._pools.values():
            await pool.aclose()
        self._pools.clear()


class MemoryQueue(Queue):
    def __init__(self) -> None:
        self.jobs: list[tuple[str, str, dict[str, Any]]] = []

    async def enqueue(
        self,
        queue: str,
        function: str,
        payload: dict[str, Any],
        *,
        defer: timedelta | None = None,
        job_id: str | None = None,
    ) -> None:
        self.jobs.append((queue, function, payload))

    async def depth(self, queue: str) -> int:
        return len([j for j in self.jobs if j[0] == queue])

    async def close(self) -> None:
        self.jobs.clear()


_queue: Queue | None = None


def get_queue() -> Queue:
    global _queue
    if _queue is None:
        _queue = MemoryQueue() if get_settings().queue_backend == "memory" else RedisQueue()
    return _queue


def set_queue(queue: Queue | None) -> None:
    global _queue
    _queue = queue


async def enqueue_asr(
    call_id: UUID,
    *,
    defer_seconds: int = 0,
    job_id: str | None = None,
    recovery: bool = False,
) -> None:
    await get_queue().enqueue(
        QUEUE_ASR,
        JOB_ASR,
        {"call_id": str(call_id), "recovery": recovery},
        defer=timedelta(seconds=defer_seconds) if defer_seconds > 0 else None,
        job_id=job_id,
    )


async def enqueue_llm(
    call_id: UUID,
    analysis_run_id: UUID | None,
    *,
    reanalysis: bool = False,
    previous_status: str | None = None,
    defer_seconds: int = 0,
    job_id: str | None = None,
    recovery: bool = False,
) -> None:
    await get_queue().enqueue(
        QUEUE_LLM,
        JOB_LLM,
        {
            "call_id": str(call_id),
            "analysis_run_id": str(analysis_run_id) if analysis_run_id is not None else None,
            "reanalysis": reanalysis,
            "previous_status": previous_status,
            "recovery": recovery,
        },
        defer=timedelta(seconds=defer_seconds) if defer_seconds > 0 else None,
        job_id=job_id,
    )


async def enqueue_emotion(
    call_id: UUID,
    analysis_run_id: UUID,
    *,
    defer_seconds: int = 0,
    job_id: str | None = None,
    recovery: bool = False,
) -> None:
    await get_queue().enqueue(
        QUEUE_EMOTION,
        JOB_EMOTION,
        {
            "call_id": str(call_id),
            "analysis_run_id": str(analysis_run_id),
            "recovery": recovery,
        },
        defer=timedelta(seconds=defer_seconds) if defer_seconds > 0 else None,
        job_id=job_id,
    )


async def enqueue_notify(
    call_id: UUID,
    event: str,
    *,
    defer_seconds: int = 0,
    job_id: str | None = None,
) -> None:
    await get_queue().enqueue(
        QUEUE_NOTIFY,
        JOB_NOTIFY,
        {"call_id": str(call_id), "event": event},
        defer=timedelta(seconds=defer_seconds) if defer_seconds > 0 else None,
        job_id=job_id,
    )


async def enqueue_balance_low(tenant_id: UUID) -> None:
    await get_queue().enqueue(
        QUEUE_NOTIFY,
        JOB_NOTIFY,
        {"event": "balance.low", "tenant_id": str(tenant_id)},
        job_id=f"balance-low:{tenant_id}:{datetime.now(UTC):%Y-%m-%d}",
    )


async def enqueue_raw(
    queue_name: str,
    function_name: str,
    payload: dict[str, Any],
    *,
    defer_seconds: int = 0,
    job_id: str | None = None,
) -> None:
    await get_queue().enqueue(
        queue_name,
        function_name,
        payload,
        defer=timedelta(seconds=defer_seconds) if defer_seconds > 0 else None,
        job_id=job_id,
    )
