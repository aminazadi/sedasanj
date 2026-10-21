"""GPU discovery, administrator policy, and per-device inference leases."""

import csv
import io
import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from asr_service.infrastructure.storage import execute, row, rows


_current_gpu = ContextVar("asr_current_gpu", default=None)
_lock = threading.Condition()
_active = {}
_last_errors = {}
_oom_counts = {}
_effective_limits = {}
_success_streaks = {}
_oom_split_models = set()
_device_cache = {"at": 0.0, "value": []}
_capability_cache = {"at": 0.0, "value": {}}
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


def runtime_capabilities():
    """Probe installed local backends without importing GPU libraries eagerly."""
    with _lock:
        if time.monotonic() - _capability_cache["at"] < 30:
            return dict(_capability_cache["value"])
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
    with _lock:
        _capability_cache.update(at=time.monotonic(), value=dict(result))
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
    if not cuda_model_family(kind, model_id):
        return False
    capabilities = runtime_capabilities()
    if kind == "asr":
        return capabilities["ctranslate2"]
    if kind in {"chat", "chat_async", "text"}:
        return capabilities["llama_cpp"]
    if kind == "decision":
        return capabilities["torch"]
    if kind == "embedding":
        return capabilities["torch"]
    return False


def cuda_model_family(kind, model_id):
    from asr_service.domain.catalog import CATALOG

    model = CATALOG.get(model_id)
    if not model:
        return False
    if kind == "asr":
        return model.architecture == "fasterWhisper"
    if kind in {"chat", "chat_async", "text"}:
        return model.kind == "llm"
    if kind == "decision":
        return model.kind == "decision" and model.engine == "laya_multilingual"
    return kind == "embedding" and model.kind == "embedding"


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


def model_memory_estimate(model_id):
    from asr_service.domain.catalog import CATALOG
    from asr_service.infrastructure.storage import MODEL_DIR

    model = CATALOG.get(model_id)
    if not model or model.kind != "llm" or not model.files:
        return 0
    path = MODEL_DIR / model_id / model.files[0].filename
    try:
        required = path.stat().st_size
    except OSError:
        required = model.files[0].expected_size or 0
    if not required:
        return 0
    return int(required * 1.15)


def split_devices(kind, model_id):
    if kind not in {"chat", "chat_async", "text"}:
        return []
    devices = enabled_devices()
    if len(devices) < 2:
        return []
    required = model_memory_estimate(model_id)
    if not required:
        return []
    safety = int(get_settings()["min_free_vram_mb"]) * 1024 * 1024
    with _lock:
        forced = model_id in _oom_split_models
    usable = [(max(0, device["memory_total"] - safety), device) for device in devices]
    if not forced and max(capacity for capacity, _ in usable) >= required:
        return []
    ordered = sorted(usable, key=lambda item: (-item[0], -item[1]["memory_free"]))
    selected = []
    capacity = 0
    for available, device in ordered:
        selected.append(device)
        capacity += available
        if len(selected) >= 2 and capacity >= required:
            return selected
    return []


def requires_multi_gpu(kind, model_id):
    return bool(split_devices(kind, model_id))


def note_model_oom(model_id, message):
    lowered = str(message).lower()
    if "out of memory" in lowered or "cuda_error_out_of_memory" in lowered:
        with _lock:
            _oom_split_models.add(model_id)
            _lock.notify_all()


def forget_model(model_id):
    with _lock:
        _oom_split_models.discard(model_id)


def record_error(device_id, message):
    identifiers = device_id.split(",") if isinstance(device_id, str) else [device_id]
    with _lock:
        lowered = str(message).lower()
        for identifier in identifiers:
            _last_errors[identifier] = {"message": str(message)[:300], "at": time.time()}
            if "out of memory" in lowered or "cuda_error_out_of_memory" in lowered:
                _oom_counts[identifier] = _oom_counts.get(identifier, 0) + 1
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
def reserve_group(devices, timeout=0, required_bytes=0):
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
                and sum(max(0, current[item]["memory_free"] - minimum) for item in identifiers if item in current) >= required_bytes
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
        oom_counts = dict(_oom_counts)
    try:
        counts = rows(
            """SELECT device_id,status,count(*) AS n FROM task_runs
               WHERE device_id IS NOT NULL AND status IN ('processing','succeeded','failed')
               GROUP BY device_id,status"""
        )
    except Exception:
        counts = []
    by_device = {}
    for item in counts:
        for identifier in item["device_id"].split(","):
            by_device.setdefault(identifier, {})[item["status"]] = item["n"]
    for device in devices:
        outcomes = by_device.get(device["uuid"], {})
        completed = outcomes.get("succeeded", 0) + outcomes.get("failed", 0)
        device.update({
            "selected": device["uuid"] in enabled,
            "enabled": device["uuid"] in enabled and settings["mode"] != "cpu",
            "active": active.get(device["uuid"], 0),
            "max_concurrent": settings["max_concurrent_per_device"],
            "effective_max_concurrent": min(settings["max_concurrent_per_device"], _effective_limits.get(device["uuid"], 1)),
            "last_error": errors.get(device["uuid"]),
            "oom_count": oom_counts.get(device["uuid"], 0),
            "succeeded": outcomes.get("succeeded", 0),
            "failed": outcomes.get("failed", 0),
            "success_rate": round(outcomes.get("succeeded", 0) / completed, 4) if completed else None,
        })
    return {
        "mode": settings["mode"], "devices": devices,
        "runtime_capabilities": capabilities,
        "cpu_fallback_seconds": settings["cpu_fallback_seconds"],
        "min_free_vram_mb": settings["min_free_vram_mb"],
    }
