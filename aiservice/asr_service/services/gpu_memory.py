"""Idle-time GPU cache trimming and pressure-driven eviction of idle resident models.

Resident models are kept on purpose (reloading is slow). What this module adds:

* ``trim_when_idle`` returns allocator caches (PyTorch) to the driver once the GPU has
  been idle for a while, never after every request, so bursts keep a warm allocator.
* ``evict_idle`` frees *idle* (not leased) resident models on one GPU when another job
  does not fit; models in use are never touched.

Everything here is a no-op when ``ASR_GPU_MEMORY_MANAGER=0``.
"""

import gc
import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)


def _float_env(name, default):
    try:
        return max(0.0, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return float(default)


def enabled():
    return os.getenv("ASR_GPU_MEMORY_MANAGER", "1").strip().lower() not in {"0", "false", "no", "off"}


_lock = threading.Lock()
_active_jobs = 0
_last_activity = time.monotonic()
_trim_pending = False
_unload_pending = False
_thread = None
_evictors = {}


def idle_trim_seconds():
    return _float_env("ASR_GPU_IDLE_TRIM_SECONDS", "10")


def idle_unload_seconds():
    """Idle window before resident models are released; 0 keeps them loaded."""
    return _float_env("ASR_GPU_IDLE_UNLOAD_SECONDS", "5")


def register_idle_evictor(name, evictor):
    """Register ``evictor(device_index) -> int`` that frees idle resident models."""
    _evictors[name] = evictor


def trim_now():
    """Collect garbage and hand PyTorch's cached-but-unused blocks back to the driver."""
    gc.collect()
    torch = sys.modules.get("torch")  # never import torch just to trim it
    if torch is None:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        logger.warning("GPU cache trim failed", exc_info=True)


def job_started():
    global _active_jobs, _last_activity
    with _lock:
        _active_jobs += 1
        _last_activity = time.monotonic()


def job_finished():
    """Record that a GPU job ended; schedules one trim after the idle window."""
    global _active_jobs, _last_activity, _trim_pending, _unload_pending
    if not enabled():
        with _lock:
            _active_jobs = max(0, _active_jobs - 1)
        return
    with _lock:
        _active_jobs = max(0, _active_jobs - 1)
        _last_activity = time.monotonic()
        _trim_pending = True
        _unload_pending = True
    _ensure_thread()


def _ensure_thread():
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_run, name="gpu-idle-trim", daemon=True)
        _thread.start()


def trim_when_idle_due(now=None):
    """Trim once if no GPU job is active and the idle window has elapsed."""
    global _trim_pending
    now = time.monotonic() if now is None else now
    with _lock:
        due = _trim_pending and _active_jobs == 0 and now - _last_activity >= idle_trim_seconds()
        if due:
            _trim_pending = False
    if due:
        trim_now()
    return due


def unload_when_idle_due(now=None):
    """Release idle resident models on every GPU once no job has run for the idle window."""
    global _unload_pending, _trim_pending
    window = idle_unload_seconds()
    if not window:
        return False
    now = time.monotonic() if now is None else now
    with _lock:
        due = _unload_pending and _active_jobs == 0 and now - _last_activity >= window
        if due:
            _unload_pending = False
    if not due:
        return False
    from . import gpu_runtime

    for device in gpu_runtime.discover_gpus():
        evict_idle(device["index"])
    trim_now()
    with _lock:
        _trim_pending = False
    return True


def _run():
    while True:
        time.sleep(1.0)
        try:
            unload_when_idle_due()
            trim_when_idle_due()
        except Exception:
            logger.warning("GPU idle trim loop error", exc_info=True)


def evict_idle(device_index):
    """Free idle resident models on one GPU; returns how many were released."""
    if not enabled():
        return 0
    released = 0
    for name, evictor in list(_evictors.items()):
        try:
            released += int(evictor(device_index) or 0)
        except Exception:
            logger.warning("Idle eviction failed for %s", name, exc_info=True)
    if released:
        trim_now()
        logger.info("Released %d idle resident model(s) on GPU %s under memory pressure", released, device_index)
    return released
