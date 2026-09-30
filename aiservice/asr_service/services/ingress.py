"""Bounded HTTP and upload admission primitives."""

import asyncio
import os
import shutil
from contextlib import asynccontextmanager

from asr_service.infrastructure.storage import row


def _positive_int(name, default):
    try:
        return max(1, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return int(default)


def _positive_float(name, default):
    try:
        return max(0.01, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return float(default)


HTTP_MAX_IN_FLIGHT = _positive_int("ASR_HTTP_MAX_IN_FLIGHT", "128")
SYNC_CHAT_MAX_IN_FLIGHT = _positive_int("ASR_SYNC_CHAT_MAX_IN_FLIGHT", "16")
HTTP_ADMISSION_WAIT_SECONDS = _positive_float(
    "ASR_HTTP_ADMISSION_WAIT_SECONDS", ".25"
)
HTTP_MAX_BODY_BYTES = _positive_int("ASR_HTTP_MAX_BODY_MB", "520") * 1024 * 1024
HTTP_MAX_JSON_BODY_BYTES = (
    _positive_int("ASR_HTTP_MAX_JSON_BODY_MB", "2") * 1024 * 1024
)
MAX_CONCURRENT_UPLOADS = _positive_int("ASR_MAX_CONCURRENT_UPLOADS", "4")
UPLOAD_ADMISSION_WAIT_SECONDS = _positive_float(
    "ASR_UPLOAD_ADMISSION_WAIT_SECONDS", ".25"
)
SPOOL_MAX_BYTES = _positive_int("ASR_SPOOL_MAX_MB", "8192") * 1024 * 1024
SPOOL_MIN_FREE_BYTES = _positive_int("ASR_SPOOL_MIN_FREE_MB", "2048") * 1024 * 1024
SPOOL_MIN_FREE_PERCENT = min(
    50.0, _positive_float("ASR_SPOOL_MIN_FREE_PERCENT", "10")
)

_upload_slots = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)


class UploadCapacityError(RuntimeError):
    pass


@asynccontextmanager
async def upload_slot():
    try:
        await asyncio.wait_for(
            _upload_slots.acquire(), timeout=UPLOAD_ADMISSION_WAIT_SECONDS
        )
    except TimeoutError as exc:
        raise UploadCapacityError("Too many uploads are active") from exc
    try:
        yield
    finally:
        _upload_slots.release()


def ensure_spool_capacity(path, incoming_bytes=0):
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    required_free = max(
        SPOOL_MIN_FREE_BYTES,
        int(usage.total * SPOOL_MIN_FREE_PERCENT / 100),
    )
    if usage.free < required_free:
        raise UploadCapacityError("Insufficient spool disk headroom")
    queued = row(
        "SELECT coalesce(sum(audio_bytes),0) AS bytes FROM tasks "
        "WHERE status IN ('queued','retrying','running') AND kind='asr'"
    )
    if int((queued or {}).get("bytes") or 0) + incoming_bytes > SPOOL_MAX_BYTES:
        raise UploadCapacityError("Audio spool capacity is full")
