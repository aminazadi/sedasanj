"""GPU discovery, administrator policy, and per-device inference leases."""

import csv
import io
import json
import os
import subprocess
import threading
import time
from functools import lru_cache
from contextlib import contextmanager
from contextvars import ContextVar

from asr_service.infrastructure.storage import execute, row


_current_gpu = ContextVar("asr_current_gpu", default=None)
_lock = threading.Condition()
_active = {}
_last_errors = {}
_effective_limits = {}
_success_streaks = {}
_device_cache = {"at": 0.0, "value": []}
CPU_FALLBACK_SECONDS = max(0, int(os.getenv("ASR_GPU_CPU_FALLBACK_SECONDS", "30")))
GPU_MIN_FREE_BYTES = max(0, int(os.getenv("ASR_GPU_MIN_FREE_MB", "1024"))) * 1024 * 1024
GPU_MAX_CONCURRENT = max(1, int(os.getenv("ASR_GPU_MAX_CONCURRENT", "1")))


def discover_gpus():
    """Return NVIDIA devices visible to this container, or an empty list."""
    with _lock:
        if time.monotonic() - _device_cache["at"] < 1:
            return [dict(item) for item in _device_cache["value"]]
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        with _lock:
            _device_cache.update(at=time.monotonic(), value=[])
        return []
    devices = []
    for values in csv.reader(io.StringIO(result.stdout), skipinitialspace=True):
        if len(values) != 6:
            continue
        try:
            index, uuid, name = int(values[0]), values[1], values[2]
            total, free, utilization = (int(value) for value in values[3:])
        except (TypeError, ValueError):
            continue
        devices.append({
            "index": index, "uuid": uuid, "name": name,
            "memory_total": total * 1024 * 1024,
            "memory_free": free * 1024 * 1024,
            "utilization_percent": utilization,
        })
    with _lock:
        _device_cache.update(at=time.monotonic(), value=[dict(item) for item in devices])
    return devices


def _default_settings():
    return {
        "mode": os.getenv("ASR_GPU_MODE", "auto"),
        "enabled_devices": [device["uuid"] for device in discover_gpus()],
        "max_concurrent_per_device": GPU_MAX_CONCURRENT,
        "min_free_vram_mb": GPU_MIN_FREE_BYTES // (1024 * 1024),
        "cpu_fallback_seconds": CPU_FALLBACK_SECONDS,
        "large_model_policy": "split_when_needed",
    }


def get_settings():
    saved = row("SELECT value FROM settings WHERE key='gpu_runtime'")
    result = _default_settings()
    if saved:
        try:
            value = json.loads(saved["value"])
            if isinstance(value, dict):
                result.update(value)
        except (TypeError, ValueError):
            pass
    return result


def save_settings(value):
    current = get_settings()
    current.update(value)
    current["mode"] = current["mode"] if current["mode"] in {"auto", "cpu", "gpu"} else "auto"
    current["max_concurrent_per_device"] = min(8, max(1, int(current["max_concurrent_per_device"])))
    current["min_free_vram_mb"] = min(65536, max(0, int(current["min_free_vram_mb"])))
    current["cpu_fallback_seconds"] = min(3600, max(0, int(current["cpu_fallback_seconds"])))
    current["large_model_policy"] = "split_when_needed"
    present = {device["uuid"] for device in discover_gpus()}
    enabled = current.get("enabled_devices", sorted(present))
    if not isinstance(enabled, list) or any(item not in present for item in enabled):
        raise ValueError("enabled_devices must contain visible GPU UUIDs")
    current["enabled_devices"] = list(dict.fromkeys(enabled))
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES('gpu_runtime',?)", (json.dumps(current, separators=(",", ":")),))
    with _lock:
        _lock.notify_all()
    return current


@lru_cache(maxsize=1)
def runtime_capabilities():
    """Probe installed local backends without importing GPU libraries eagerly."""
    result = {"ctranslate2": False, "llama_cpp": False, "torch": False}
    try:
        import ctranslate2
        result["ctranslate2"] = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass
    try:
        from llama_cpp import llama_supports_gpu_offload
        result["llama_cpp"] = bool(llama_supports_gpu_offload())
    except Exception:
        pass
    try:
        import torch
        result["torch"] = bool(torch.cuda.is_available())
    except Exception:
        pass
    return result


def enabled_devices():
    settings = get_settings()
    if settings["mode"] == "cpu":
        return []
    selected = set(settings.get("enabled_devices") or ())
    return [device for device in discover_gpus() if device["uuid"] in selected]


def gpu_eligible(kind, model_id):
    """Whether the selected model family has a verified CUDA runtime."""
    devices = enabled_devices()
    if not devices:
        return False
    from asr_service.domain.catalog import CATALOG

    model = CATALOG.get(model_id)
    if not model:
        return False
    capabilities = runtime_capabilities()
    if kind == "asr":
        return model.architecture == "fasterWhisper" and capabilities["ctranslate2"]
    if kind in {"chat", "chat_async", "text"}:
        return model.kind == "llm" and capabilities["llama_cpp"]
    if kind == "decision":
        return model.kind == "decision" and model.engine == "laya_multilingual" and capabilities["torch"]
    if kind == "embedding":
        return model.kind == "embedding" and capabilities["torch"]
    return False


def gpu_wait_seconds():
    return get_settings()["cpu_fallback_seconds"]


def current_device():
    return _current_gpu.get()


def current_device_index():
    device = current_device()
    if device:
        return device["index"]
    try:
        return int(os.getenv("ASR_ASSIGNED_GPU_INDEX", ""))
    except ValueError:
        return None


def current_is_split():
    device = current_device()
    return bool(device and device.get("split")) or os.getenv("ASR_ASSIGNED_GPU_SPLIT") == "1"


def current_device_indices():
    device = current_device()
    if device and device.get("indices"):
        return device["indices"]
    assigned = os.getenv("ASR_ASSIGNED_GPU_INDICES")
    if assigned:
        try:
            return [int(value) for value in assigned.split(",")]
        except ValueError:
            return []
    index = current_device_index()
    return [index] if index is not None else []


def requires_multi_gpu(kind, model_id):
    if kind not in {"chat", "chat_async", "text"}:
        return False
    devices = enabled_devices()
    if len(devices) < 2:
        return False
    from asr_service.domain.catalog import CATALOG
    from asr_service.infrastructure.storage import MODEL_DIR

    model = CATALOG.get(model_id)
    if not model or model.kind != "llm" or not model.files:
        return False
    path = MODEL_DIR / model_id / model.files[0].filename
    try:
        required = path.stat().st_size
    except OSError:
        required = model.files[0].expected_size or 0
    if not required:
        return False
    safety = int(get_settings()["min_free_vram_mb"]) * 1024 * 1024
    required = int(required * 1.15) + safety
    return max(device["memory_free"] for device in devices) < required <= sum(device["memory_free"] for device in devices) - safety


def record_error(device_id, message):
    identifiers = device_id.split(",") if isinstance(device_id, str) else [device_id]
    with _lock:
        lowered = str(message).lower()
        for identifier in identifiers:
            _last_errors[identifier] = {"message": str(message)[:300], "at": time.time()}
            if "out of memory" in lowered or "cuda_error_out_of_memory" in lowered:
                _effective_limits[identifier] = max(1, _effective_limits.get(identifier, 1) - 1)
                _success_streaks[identifier] = 0
        _lock.notify_all()


def record_success(device_id):
    limit = int(get_settings()["max_concurrent_per_device"])
    identifiers = device_id.split(",") if isinstance(device_id, str) else [device_id]
    with _lock:
        for identifier in identifiers:
            _success_streaks[identifier] = _success_streaks.get(identifier, 0) + 1
            if _success_streaks[identifier] >= 10:
                _effective_limits[identifier] = min(limit, _effective_limits.get(identifier, 1) + 1)
                _success_streaks[identifier] = 0
        _lock.notify_all()


@contextmanager
def reserve_group(devices, timeout=0):
    """Atomically reserve every enabled GPU for a model that needs sharding."""
    devices = sorted(devices, key=lambda item: item["uuid"])
    identifiers = [device["uuid"] for device in devices]
    if len(devices) < 2:
        raise TimeoutError("Multi-GPU capacity is unavailable")
    deadline = time.monotonic() + timeout
    token = None
    while True:
        settings = get_settings()
        current = {item["uuid"]: item for item in discover_gpus()}
        minimum = int(settings["min_free_vram_mb"]) * 1024 * 1024
        with _lock:
            available = (
                settings["mode"] != "cpu"
                and set(identifiers) <= set(settings.get("enabled_devices") or ())
                and all(item in current and current[item]["memory_free"] >= minimum for item in identifiers)
                and all(_active.get(item, 0) == 0 for item in identifiers)
            )
            if available:
                for item in identifiers:
                    _active[item] = 1
                primary = current[identifiers[0]]
                context = dict(primary, uuid=",".join(identifiers), split=True, indices=[current[item]["index"] for item in identifiers])
                token = _current_gpu.set(context)
                break
        if time.monotonic() >= deadline:
            raise TimeoutError("Multi-GPU capacity is currently full")
        with _lock:
            _lock.wait(min(.25, max(.01, deadline - time.monotonic())))
    try:
        yield context
    finally:
        if token is not None:
            _current_gpu.reset(token)
        with _lock:
            for item in identifiers:
                _active[item] = max(0, _active.get(item, 1) - 1)
            _lock.notify_all()


@contextmanager
def reserve(device, timeout=0):
    """Reserve one physical GPU and expose it to model loaders in this thread."""
    device_id = device["uuid"]
    token = None
    deadline = time.monotonic() + timeout
    while True:
        settings = get_settings()
        current = next((item for item in discover_gpus() if item["uuid"] == device_id), None)
        limit = min(int(settings["max_concurrent_per_device"]), _effective_limits.get(device_id, 1))
        floor = int(settings["min_free_vram_mb"]) * 1024 * 1024
        with _lock:
            active = _active.get(device_id, 0)
            if current and device_id in set(settings.get("enabled_devices") or ()) and settings["mode"] != "cpu" and current["memory_free"] >= floor and active < limit:
                _active[device_id] = active + 1
                token = _current_gpu.set(current)
                break
        if time.monotonic() >= deadline:
            raise TimeoutError("GPU capacity is currently full")
        with _lock:
            _lock.wait(min(.25, max(.01, deadline - time.monotonic())))
    try:
        yield current
    finally:
        if token is not None:
            _current_gpu.reset(token)
        with _lock:
            _active[device_id] = max(0, _active.get(device_id, 1) - 1)
            _lock.notify_all()


def snapshot():
    settings = get_settings()
    devices = discover_gpus()
    enabled = set(settings.get("enabled_devices") or ())
    capabilities = runtime_capabilities()
    with _lock:
        active = dict(_active)
        errors = dict(_last_errors)
    for device in devices:
        device.update({
            "enabled": device["uuid"] in enabled and settings["mode"] != "cpu",
            "active": active.get(device["uuid"], 0),
            "max_concurrent": settings["max_concurrent_per_device"],
            "effective_max_concurrent": min(settings["max_concurrent_per_device"], _effective_limits.get(device["uuid"], 1)),
            "last_error": errors.get(device["uuid"]),
        })
    return {
        "mode": settings["mode"], "devices": devices,
        "runtime_capabilities": capabilities,
        "cpu_fallback_seconds": settings["cpu_fallback_seconds"],
        "min_free_vram_mb": settings["min_free_vram_mb"],
    }
