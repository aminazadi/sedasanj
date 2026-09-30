"""Process-wide inference capacity and CPU-thread budgeting."""

import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path


def _positive_int(name, default):
    try:
        return max(1, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return max(1, int(default))


def _nonnegative_int(name, default):
    try:
        return max(0, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return max(0, int(default))


def _affinity_cpus():
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _cgroup_quota_cpus():
    """Return the CPU quota visible to this process for cgroup v1 or v2."""
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            return max(1, int(quota) // int(period))
    except (OSError, ValueError, ZeroDivisionError):
        pass
    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0:
            return max(1, quota // period)
    except (OSError, ValueError, ZeroDivisionError):
        pass
    return None


def _physical_cpus():
    """Best-effort physical-core count, falling back conservatively."""
    roots = (Path("/host/sys/devices/system/cpu"), Path("/sys/devices/system/cpu"))
    for root in roots:
        cores = set()
        try:
            for cpu in root.glob("cpu[0-9]*"):
                package = (cpu / "topology/physical_package_id").read_text().strip()
                core = (cpu / "topology/core_id").read_text().strip()
                cores.add((package, core))
        except OSError:
            cores.clear()
        if cores:
            return len(cores)
    # This helper is evaluated while module-level CPU_CAPACITY is being built,
    # so do not reference that later global here.
    visible = _cgroup_quota_cpus() or _affinity_cpus()
    return max(1, visible // 2)


CPU_CAPACITY = min(
    value for value in (_affinity_cpus(), _cgroup_quota_cpus()) if value is not None
)
try:
    CPU_BUDGET_PERCENT = min(95.0, max(1.0, float(os.getenv("ASR_CPU_BUDGET_PERCENT", "90"))))
except ValueError:
    CPU_BUDGET_PERCENT = 90.0
# Native inference libraries use whole worker threads.  Rounding down keeps the
# process under the requested budget on multi-core hosts (e.g. 30/32 = 93.75%).
# A single vCPU cannot be fractionally limited by a thread count; use a Docker
# CPU quota in that case when an exact 95% ceiling is required.
CPU_BUDGET_CORES = max(1, int(CPU_CAPACITY * CPU_BUDGET_PERCENT / 100))
# Zero means automatic. Keep at least four threads per CPU inference and cap the
# worker fan-out so model/RAM costs cannot explode before feedback catches up.
MIN_THREADS_PER_JOB = _positive_int("ASR_MIN_THREADS_PER_JOB", "4")
AUTO_CONCURRENCY = min(
    _positive_int("ASR_AUTO_MAX_CONCURRENT", "8"),
    max(1, CPU_BUDGET_CORES // MIN_THREADS_PER_JOB),
)
_requested_concurrency = _nonnegative_int("ASR_MAX_CONCURRENT", "0")
INFERENCE_SLOTS = min(
    _requested_concurrency or AUTO_CONCURRENCY, CPU_BUDGET_CORES
)
_requested_workers = _nonnegative_int("ASR_TASK_WORKERS", "0")
TASK_WORKERS = min(
    _requested_workers or INFERENCE_SLOTS, INFERENCE_SLOTS
)
LLM_MAX_CONCURRENT = min(
    _positive_int("ASR_LLM_MAX_CONCURRENT", "2"), INFERENCE_SLOTS
)
DECISION_MAX_CONCURRENT = min(
    _positive_int("ASR_DECISION_MAX_CONCURRENT", "2"), INFERENCE_SLOTS
)
try:
    _requested_threads = int(os.getenv("ASR_CPU_THREADS", "0"))
except ValueError:
    _requested_threads = 0

_fair_share = max(1, CPU_BUDGET_CORES // INFERENCE_SLOTS)
ASR_CPU_THREADS = _fair_share if _requested_threads <= 0 else min(_requested_threads, _fair_share)
# llama.cpp generation generally benefits from physical rather than SMT thread
# count. LLM jobs are serialized below, so they can safely use this larger share.
LLM_CPU_THREADS = (
    min(CPU_BUDGET_CORES // LLM_MAX_CONCURRENT, _physical_cpus())
    if _requested_threads <= 0
    else min(_requested_threads, max(1, CPU_BUDGET_CORES // LLM_MAX_CONCURRENT))
)
DECISION_CPU_THREADS = min(
    _positive_int("ASR_DECISION_CPU_THREADS", "7"),
    max(1, CPU_BUDGET_CORES // DECISION_MAX_CONCURRENT),
)
CPU_THREADS = ASR_CPU_THREADS

# A full inference slot is normal backpressure, not a request error.  Chat
# callers therefore wait for their turn just like durable ASR/text tasks.  Do
# not read a deployment timeout here: a stale `.env` value previously turned a
# burst of otherwise valid requests into 503 responses.
INFERENCE_WAIT_SECONDS = None


def _percent_setting(name, default):
    try:
        return min(95.0, max(1.0, float(os.getenv(name, default))))
    except ValueError:
        return float(default)


ADMISSION_CPU_PERCENT = _percent_setting("ASR_ADMISSION_CPU_PERCENT", 80)
ADMISSION_MEMORY_PERCENT = _percent_setting("ASR_ADMISSION_MEMORY_PERCENT", 80)


def _pressure_avg10(resource, kind="some"):
    for root in (Path(os.getenv("ASR_HOST_PROC", "/host/proc")), Path("/proc")):
        try:
            for line in (root / "pressure" / resource).read_text().splitlines():
                parts = line.split()
                if parts and parts[0] == kind:
                    return float(next(x.split("=", 1)[1] for x in parts[1:] if x.startswith("avg10=")))
        except (OSError, ValueError, StopIteration):
            continue
    return 0.0


class AdaptiveAdmissionController:
    """AIMD-style capacity controller with smoothing and hysteresis."""

    def __init__(self, hard_limit):
        self.hard_limit = hard_limit
        self.initial_target = min(
            hard_limit, _positive_int("ASR_INITIAL_CONCURRENT", "1")
        )
        self.target = self.initial_target
        self.cpu_ema = self.memory_ema = 0.0
        self.low_samples = 0
        self.last_sample = self.last_increase = 0.0
        self.lock = threading.Lock()

    def update(self, metrics, active, demand=True):
        stamp = time.monotonic()
        with self.lock:
            if stamp - self.last_sample < 1.0:
                return active < self.target
            self.last_sample = stamp
            container = metrics.get("container") or {}
            cpu = max(float(metrics["cpu"]["percent"]), float(container.get("cpu_percent", 0)))
            memory = max(float(metrics["memory"]["percent"]), float((container.get("memory") or {}).get("percent", 0)))
            alpha = .3
            self.cpu_ema = cpu if not self.cpu_ema else alpha * cpu + (1 - alpha) * self.cpu_ema
            self.memory_ema = memory if not self.memory_ema else alpha * memory + (1 - alpha) * self.memory_ema
            if not demand:
                self.low_samples = 0
                if active == 0:
                    self.target = self.initial_target
                return False
            pressured = _pressure_avg10("cpu") >= 10 or _pressure_avg10("memory", "full") >= 1
            # Raw threshold stops a burst immediately; EMA keeps admission
            # suppressed until sustained pressure has actually subsided.
            high = cpu >= ADMISSION_CPU_PERCENT or memory >= ADMISSION_MEMORY_PERCENT or self.cpu_ema >= ADMISSION_CPU_PERCENT or self.memory_ema >= ADMISSION_MEMORY_PERCENT or pressured
            low = self.cpu_ema < ADMISSION_CPU_PERCENT - 15 and self.memory_ema < ADMISSION_MEMORY_PERCENT - 10 and not pressured
            if high:
                self.low_samples = 0
                self.target = max(1, min(self.target - 1, active))
            elif low:
                self.low_samples += 1
                if self.low_samples >= 3 and stamp - self.last_increase >= 5 and self.target < self.hard_limit:
                    self.target += 1
                    self.low_samples = 0
                    self.last_increase = stamp
            else:
                self.low_samples = 0
            return active < self.target


_controller = AdaptiveAdmissionController(INFERENCE_SLOTS)


def admission_allowed(demand=True):
    """Whether starting one more job leaves a safe CPU/RAM headroom."""
    # Import lazily: system_monitor imports this module for CPU_CAPACITY.
    from .system_monitor import snapshot

    metrics = snapshot()
    with _slot_condition:
        active = _active_slots
    allowed = _controller.update(metrics, active, demand)
    if allowed:
        with _slot_condition:
            _slot_condition.notify_all()
    return allowed


class InferenceCapacityError(RuntimeError):
    pass


_slot_condition = threading.Condition()
_active_slots = 0
_slot_waiters = deque()


def scheduler_state():
    with _slot_condition, _controller.lock:
        return {
            "mode": "adaptive" if _requested_concurrency == 0 else "fixed_ceiling_adaptive_admission",
            "active": _active_slots,
            "target": _controller.target,
            "hard_limit": INFERENCE_SLOTS,
            "workers": TASK_WORKERS,
            "llm_max_concurrent": LLM_MAX_CONCURRENT,
            "asr_threads_per_job": ASR_CPU_THREADS,
            "llm_threads_per_job": LLM_CPU_THREADS,
            "decision_max_concurrent": DECISION_MAX_CONCURRENT,
            "decision_threads_per_job": DECISION_CPU_THREADS,
            "cpu_ema_percent": round(_controller.cpu_ema, 1),
            "memory_ema_percent": round(_controller.memory_ema, 1),
            "cpu_stop_percent": ADMISSION_CPU_PERCENT,
            "memory_stop_percent": ADMISSION_MEMORY_PERCENT,
        }


@contextmanager
def inference_slot(timeout=None):
    """Acquire shared native-inference capacity in FIFO order.

    A single ASR/LLM process must never let later chat requests jump ahead of
    earlier ones.  ``timeout=0`` remains available to queue workers, which
    poll instead of blocking; API calls use the default unbounded wait.
    """
    global _active_slots
    token = object()
    with _slot_condition:
        _slot_waiters.append(token)
        deadline = None if timeout is None else time.monotonic() + timeout
        while _slot_waiters[0] is not token or _active_slots >= min(INFERENCE_SLOTS, _controller.target):
            if deadline is None:
                _slot_condition.wait()
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _slot_waiters.remove(token)
                _slot_condition.notify_all()
                raise InferenceCapacityError("Inference capacity is currently full")
            _slot_condition.wait(remaining)
        _slot_waiters.popleft()
        _active_slots += 1
    try:
        yield
    finally:
        with _slot_condition:
            _active_slots -= 1
            _slot_condition.notify_all()
