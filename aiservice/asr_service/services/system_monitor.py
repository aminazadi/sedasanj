"""Scope-aware Linux host and container metrics for the administration dashboard."""

import os
import platform
import shutil
import socket
import threading
import time
from pathlib import Path

from .resources import CPU_CAPACITY


_lock = threading.Lock()
_previous = {
    "at": None,
    "scope": None,
    "cpu": None,
    "cgroup_cpu": None,
    "network": None,
    "container_network": None,
    "disk": None,
    "processes": {},
}


def _read(path):
    try:
        return Path(path).read_text()
    except (OSError, UnicodeError):
        return ""


def _percent(used, total):
    return round(max(0.0, min(100.0, used * 100 / total)), 1) if total else 0.0


def _proc_root():
    host = Path(os.getenv("ASR_HOST_PROC", "/host/proc"))
    if (host / "stat").is_file() and (host / "meminfo").is_file():
        return host, "host"
    return Path("/proc"), "container"


def _sys_root(scope):
    if scope == "host":
        host = Path(os.getenv("ASR_HOST_SYS", "/host/sys"))
        if host.exists():
            return host
    return Path("/sys")


def _storage_path(data_path, scope):
    """Resolve the measured filesystem without exposing the host root tree."""

    if data_path is not None:
        requested = Path(data_path)
        display_path = str(data_path)
        storage_scope = "requested"
    elif scope == "host":
        requested = Path(
            os.getenv("ASR_HOST_STORAGE_PATH", "/host/rootfs-probe")
        )
        display_path = "/"
        storage_scope = "host"
        if not requested.exists():
            requested = Path(os.getenv("ASR_DATA_DIR", "/"))
            display_path = str(requested)
            storage_scope = "container"
    else:
        requested = Path(os.getenv("ASR_DATA_DIR", "/"))
        display_path = str(requested)
        storage_scope = "container"

    while not requested.exists() and requested != requested.parent:
        requested = requested.parent
    return requested, display_path, storage_scope


def _cpu_times(proc_root):
    result = []
    for line in _read(proc_root / "stat").splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith("cpu"):
            break
        try:
            values = [int(value) for value in parts[1:]]
        except ValueError:
            continue
        idle = sum(values[index] for index in (3, 4) if index < len(values))
        result.append((sum(values), idle))
    return result


def _cpu_percent(current, previous):
    if not previous or len(previous) != len(current):
        return [0.0] * len(current)
    values = []
    for (total, idle), (old_total, old_idle) in zip(current, previous):
        elapsed = total - old_total
        values.append(_percent(elapsed - (idle - old_idle), elapsed))
    return values


def _meminfo(proc_root):
    values = {}
    for line in _read(proc_root / "meminfo").splitlines():
        key, _, raw = line.partition(":")
        try:
            values[key] = int(raw.split()[0]) * 1024
        except (ValueError, IndexError):
            continue
    return values


def _memory(proc_root, use_cgroup=False, cgroup_root=None):
    values = _meminfo(proc_root)
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(0, total - available)
    cached = max(
        0,
        values.get("Cached", 0)
        + values.get("SReclaimable", 0)
        - values.get("Shmem", 0),
    )
    free = values.get("MemFree", available)
    swap_total = values.get("SwapTotal", 0)
    swap_used = max(0, swap_total - values.get("SwapFree", 0))

    if use_cgroup:
        root = Path(cgroup_root or os.getenv("ASR_CGROUP_ROOT", "/sys/fs/cgroup"))
        limit_raw = _read(root / "memory.max").strip()
        current_raw = _read(root / "memory.current").strip()
        stat = {}
        for line in _read(root / "memory.stat").splitlines():
            key, _, raw = line.partition(" ")
            try:
                stat[key] = int(raw)
            except ValueError:
                continue
        try:
            limit, current = int(limit_raw), int(current_raw)
            if limit > 0:
                inactive_file = stat.get("inactive_file", 0)
                total = min(total, limit) if total else limit
                used = min(total, max(0, current - inactive_file))
                cached = stat.get("file", inactive_file)
                available = max(0, total - used)
                free = available
        except ValueError:
            try:
                limit = int(_read(root / "memory.limit_in_bytes").strip())
                current = int(_read(root / "memory.usage_in_bytes").strip())
                v1_stat = {}
                for line in _read(root / "memory.stat").splitlines():
                    key, _, raw = line.partition(" ")
                    try:
                        v1_stat[key] = int(raw)
                    except ValueError:
                        continue
                if 0 < limit < (1 << 60):
                    inactive_file = v1_stat.get("total_inactive_file", 0)
                    total = min(total, limit) if total else limit
                    used = min(total, max(0, current - inactive_file))
                    cached = v1_stat.get("total_cache", inactive_file)
                    available = max(0, total - used)
                    free = available
            except ValueError:
                pass
        try:
            raw_swap_max = _read(root / "memory.swap.max").strip()
            raw_swap_current = _read(root / "memory.swap.current").strip()
            current_swap = int(raw_swap_current)
            if raw_swap_max == "max":
                swap_used = current_swap
                swap_total = max(swap_total, swap_used)
            else:
                swap_total = int(raw_swap_max)
                swap_used = min(swap_total, current_swap)
        except ValueError:
            pass

    return {
        "total": total,
        "used": used,
        "available": available,
        "free": free,
        "cached": cached,
        "percent": _percent(used, total),
        "swap_total": swap_total,
        "swap_used": swap_used,
        "swap_percent": _percent(swap_used, swap_total),
    }


def _network_base(proc_root, host_scope):
    host_network = proc_root / "1/net"
    return host_network if host_scope and (host_network / "dev").is_file() else proc_root / "net"


def _default_interface(proc_root, host_scope=False):
    base = _network_base(proc_root, host_scope)
    for line in _read(base / "route").splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "00000000":
            try:
                if int(fields[3], 16) & 2:
                    return fields[0]
            except ValueError:
                continue
    return None


def _network_counters(proc_root, preferred=None, host_scope=False):
    interfaces = []
    for line in _read(_network_base(proc_root, host_scope) / "dev").splitlines()[2:]:
        name, separator, raw = line.partition(":")
        fields = raw.split()
        if not separator or len(fields) < 16:
            continue
        try:
            rx, tx = int(fields[0]), int(fields[8])
        except ValueError:
            continue
        interfaces.append({"name": name.strip(), "received": rx, "sent": tx})
    names = {item["name"] for item in interfaces}
    selected = preferred if preferred in names else _default_interface(proc_root, host_scope)
    if selected not in names:
        candidates = [item for item in interfaces if item["name"] != "lo"]
        selected = (
            max(candidates, key=lambda item: item["received"] + item["sent"])["name"]
            if candidates
            else None
        )
    chosen = next((item for item in interfaces if item["name"] == selected), None)
    if chosen:
        received, sent = chosen["received"], chosen["sent"]
    else:
        received = sum(item["received"] for item in interfaces if item["name"] != "lo")
        sent = sum(item["sent"] for item in interfaces if item["name"] != "lo")
    return {
        "interface": selected,
        "received": received,
        "sent": sent,
        "interfaces": interfaces,
    }


def _disk_counters(proc_root, sys_root, device_number=None):
    devices = []
    for line in _read(proc_root / "diskstats").splitlines():
        parts = line.split()
        if len(parts) < 14 or parts[2].startswith(("loop", "ram", "fd", "sr")):
            continue
        try:
            devices.append(
                {
                    "major": int(parts[0]),
                    "minor": int(parts[1]),
                    "name": parts[2],
                    "read": int(parts[5]) * 512,
                    "write": int(parts[9]) * 512,
                }
            )
        except ValueError:
            continue
    if device_number:
        major, minor = device_number
        exact = next(
            (
                item
                for item in devices
                if (item["major"], item["minor"]) == (major, minor)
            ),
            None,
        )
        if exact:
            return exact
    whole = [
        item
        for item in devices
        if not (sys_root / "class/block" / item["name"] / "partition").exists()
    ]
    return {
        "name": None,
        "read": sum(item["read"] for item in whole),
        "write": sum(item["write"] for item in whole),
    }


def _processes(proc_root, elapsed, previous):
    clock_ticks = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")
    items, current = [], {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return [], {}, 0
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
            close = raw.rfind(")")
            fields = raw[close + 2 :].split()
            pid = int(entry.name)
            cpu_time = (int(fields[11]) + int(fields[12])) / clock_ticks
            rss = int(fields[21]) * page_size
            name = raw[raw.find("(") + 1 : close]
            current[pid] = cpu_time
            cpu = (
                max(
                    0.0,
                    (cpu_time - previous.get(pid, cpu_time)) * 100 / elapsed,
                )
                if elapsed
                else 0.0
            )
            items.append(
                {
                    "pid": pid,
                    "name": name,
                    "cpu_percent": round(cpu, 1),
                    "memory_bytes": rss,
                }
            )
        except (OSError, ValueError, IndexError):
            continue
    items.sort(
        key=lambda item: (item["cpu_percent"], item["memory_bytes"]), reverse=True
    )
    return items[:8], current, len(items)


def _cgroup_cpu_usage(cgroup_root=None):
    root = Path(cgroup_root or os.getenv("ASR_CGROUP_ROOT", "/sys/fs/cgroup"))
    for line in _read(root / "cpu.stat").splitlines():
        key, _, raw = line.partition(" ")
        if key == "usage_usec":
            try:
                return int(raw) / 1_000_000
            except ValueError:
                return None
    try:
        return int(_read(root / "cpuacct.usage").strip()) / 1_000_000_000
    except ValueError:
        return None


def _load_average(proc_root):
    try:
        return [
            round(float(value), 2)
            for value in _read(proc_root / "loadavg").split()[:3]
        ]
    except ValueError:
        try:
            return [round(value, 2) for value in os.getloadavg()]
        except OSError:
            return [0.0, 0.0, 0.0]


def _hostname(proc_root):
    return _read(proc_root / "sys/kernel/hostname").strip() or socket.gethostname()


def _rate(current, previous, key, elapsed):
    if not elapsed or not previous:
        return 0.0
    if "interface" in current and current.get("interface") != previous.get("interface"):
        return 0.0
    return max(0.0, (current[key] - previous[key]) / elapsed)


def snapshot(data_path=None):
    """Return host metrics plus an explicitly separate ASR-container summary."""

    now_monotonic = time.monotonic()
    proc_root, scope = _proc_root()
    sys_root = _sys_root(scope)
    cpu = _cpu_times(proc_root)
    preferred_interface = os.getenv(
        "ASR_HOST_NETWORK_INTERFACE"
        if scope == "host"
        else "ASR_CONTAINER_NETWORK_INTERFACE",
        "",
    )
    network = _network_counters(
        proc_root, preferred_interface or None, scope == "host"
    )
    storage_path, storage_display_path, storage_scope = _storage_path(
        data_path, scope
    )
    storage = shutil.disk_usage(storage_path)
    try:
        device_number = (
            os.major(storage_path.stat().st_dev),
            os.minor(storage_path.stat().st_dev),
        )
    except (OSError, AttributeError):
        device_number = None
    disk_io = _disk_counters(proc_root, sys_root, device_number)
    container_network = _network_counters(
        Path("/proc"), os.getenv("ASR_CONTAINER_NETWORK_INTERFACE") or None
    )
    cgroup_cpu = _cgroup_cpu_usage()

    with _lock:
        previous_scope = _previous["scope"]
        elapsed = (
            max(0.001, now_monotonic - _previous["at"])
            if _previous["at"] and previous_scope == scope
            else None
        )
        cpu_values = _cpu_percent(
            cpu, _previous["cpu"] if previous_scope == scope else None
        )
        processes, process_times, process_count = _processes(
            proc_root,
            elapsed,
            _previous["processes"] if previous_scope == scope else {},
        )
        previous_network = _previous["network"] if previous_scope == scope else None
        previous_disk = _previous["disk"] if previous_scope == scope else None
        previous_container_network = _previous["container_network"]
        previous_cgroup_cpu = _previous["cgroup_cpu"]
        _previous.update(
            at=now_monotonic,
            scope=scope,
            cpu=cpu,
            cgroup_cpu=cgroup_cpu,
            network=network,
            container_network=container_network,
            disk=disk_io,
            processes=process_times,
        )

    cores = max(1, len(cpu) - 1) if scope == "host" else CPU_CAPACITY
    if scope == "host":
        cpu_percent = cpu_values[0] if cpu_values else 0.0
        per_core = cpu_values[1:]
    else:
        cpu_percent = (
            _percent(cgroup_cpu - previous_cgroup_cpu, elapsed * CPU_CAPACITY)
            if elapsed
            and cgroup_cpu is not None
            and previous_cgroup_cpu is not None
            else (cpu_values[0] if cpu_values else 0.0)
        )
        per_core = []

    uptime_raw = _read(proc_root / "uptime").split()
    uptime = float(uptime_raw[0]) if uptime_raw else 0.0
    try:
        container_process_count = sum(
            entry.name.isdigit() for entry in Path("/proc").iterdir()
        )
    except OSError:
        container_process_count = 0
    container_cpu_percent = (
        _percent(cgroup_cpu - previous_cgroup_cpu, elapsed * CPU_CAPACITY)
        if elapsed and cgroup_cpu is not None and previous_cgroup_cpu is not None
        else 0.0
    )
    return {
        "scope": scope,
        "hostname": _hostname(proc_root),
        "platform": platform.system(),
        "uptime_seconds": uptime,
        "load_average": _load_average(proc_root),
        "cpu": {"percent": cpu_percent, "cores": cores, "per_core": per_core},
        "memory": _memory(proc_root, use_cgroup=scope != "host"),
        "disk": {
            "scope": storage_scope,
            "path": storage_display_path,
            "device": disk_io.get("name"),
            "total": storage.total,
            "used": storage.used,
            "free": storage.free,
            "percent": _percent(storage.used, storage.total),
            "read_bytes_per_second": round(
                _rate(disk_io, previous_disk, "read", elapsed)
            ),
            "write_bytes_per_second": round(
                _rate(disk_io, previous_disk, "write", elapsed)
            ),
        },
        "network": {
            **network,
            "receive_bytes_per_second": round(
                _rate(network, previous_network, "received", elapsed)
            ),
            "send_bytes_per_second": round(
                _rate(network, previous_network, "sent", elapsed)
            ),
        },
        "process_count": process_count,
        "processes": processes,
        "container": {
            "hostname": socket.gethostname(),
            "cpu_percent": container_cpu_percent,
            "cpu_capacity": CPU_CAPACITY,
            "memory": _memory(Path("/proc"), use_cgroup=True),
            "network": {
                **container_network,
                "receive_bytes_per_second": round(
                    _rate(
                        container_network,
                        previous_container_network,
                        "received",
                        elapsed,
                    )
                ),
                "send_bytes_per_second": round(
                    _rate(
                        container_network,
                        previous_container_network,
                        "sent",
                        elapsed,
                    )
                ),
            },
            "process_count": container_process_count,
        },
        "sampled_at": time.time(),
    }
