import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asr_service.services import resources


class ResourceBudgetTests(unittest.TestCase):
    def setUp(self):
        # Capacity primitives are tested independently of the adaptive ramp.
        resources._controller.target = resources.INFERENCE_SLOTS

    def test_thread_budget_never_oversubscribes_visible_cpu_capacity(self):
        self.assertGreaterEqual(resources.CPU_CAPACITY, 1)
        self.assertGreaterEqual(resources.CPU_THREADS, 1)
        self.assertLessEqual(
            resources.CPU_THREADS * resources.INFERENCE_SLOTS,
            resources.CPU_CAPACITY,
        )

    def test_capacity_is_bounded_and_released(self):
        entered = threading.Event()
        release = threading.Event()

        def hold_all_slots():
            contexts = [resources.inference_slot() for _ in range(resources.INFERENCE_SLOTS)]
            for context in contexts:
                context.__enter__()
            entered.set()
            release.wait(2)
            for context in reversed(contexts):
                context.__exit__(None, None, None)

        holder = threading.Thread(target=hold_all_slots)
        holder.start()
        self.assertTrue(entered.wait(2))
        with self.assertRaises(resources.InferenceCapacityError):
            with resources.inference_slot(timeout=0):
                pass
        release.set()
        holder.join(2)
        self.assertFalse(holder.is_alive())
        with resources.inference_slot(timeout=0):
            pass

    def test_chat_capacity_wait_is_unbounded(self):
        self.assertIsNone(resources.INFERENCE_WAIT_SECONDS)

    def test_adaptive_controller_scales_up_and_backs_off(self):
        controller = resources.AdaptiveAdmissionController(4)
        healthy = {
            "cpu": {"percent": 20},
            "memory": {"percent": 20},
            "container": {"cpu_percent": 20, "memory": {"percent": 20}},
        }
        overloaded = {
            "cpu": {"percent": 90},
            "memory": {"percent": 20},
            "container": {"cpu_percent": 90, "memory": {"percent": 20}},
        }
        with patch.object(resources, "_pressure_avg10", return_value=0), patch.object(
            resources.time, "monotonic", side_effect=[10, 11, 16, 17]
        ):
            controller.update(healthy, 0)
            controller.update(healthy, 0)
            controller.update(healthy, 0)
            self.assertEqual(controller.target, 2)
            controller.update(overloaded, 1)
            self.assertEqual(controller.target, 1)

    def test_waiting_callers_are_admitted_in_arrival_order(self):
        admitted = []
        first_waiting = threading.Event()
        second_waiting = threading.Event()

        def wait_for_slot(label, waiting):
            waiting.set()
            with resources.inference_slot():
                admitted.append(label)

        with resources.inference_slot():
            first = threading.Thread(target=wait_for_slot, args=("first", first_waiting))
            first.start()
            self.assertTrue(first_waiting.wait(1))
            for _ in range(50):
                with resources._slot_condition:
                    if len(resources._slot_waiters) == 1:
                        break
                threading.Event().wait(.01)
            second = threading.Thread(target=wait_for_slot, args=("second", second_waiting))
            second.start()
            self.assertTrue(second_waiting.wait(1))
        first.join(1)
        second.join(1)
        self.assertEqual(admitted, ["first", "second"])

    def test_system_snapshot_has_dashboard_resource_groups(self):
        from asr_service.services.system_monitor import snapshot

        with tempfile.TemporaryDirectory() as directory:
            result = snapshot(directory)
        self.assertGreaterEqual(result["cpu"]["cores"], 1)
        self.assertGreater(result["disk"]["total"], 0)
        self.assertIn("percent", result["memory"])
        self.assertIn("receive_bytes_per_second", result["network"])
        self.assertIn("container", result)
        self.assertLessEqual(len(result["processes"]), 8)

    def test_cgroup_limit_never_inflates_visible_host_memory(self):
        from asr_service.services.system_monitor import _memory

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            cgroup_root = root / "cgroup"
            proc_root.mkdir()
            cgroup_root.mkdir()
            (proc_root / "meminfo").write_text(
                "MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n"
                "MemFree: 5242880 kB\nCached: 1048576 kB\n"
                "SReclaimable: 0 kB\nShmem: 0 kB\n"
                "SwapTotal: 2097152 kB\nSwapFree: 2097152 kB\n"
            )
            (cgroup_root / "memory.max").write_text(str(32 * 1024**3))
            (cgroup_root / "memory.current").write_text(str(1024**3))
            (cgroup_root / "memory.stat").write_text("inactive_file 0\nfile 0\n")
            (cgroup_root / "memory.swap.max").write_text("max")
            (cgroup_root / "memory.swap.current").write_text(str(512 * 1024**2))
            result = _memory(proc_root, use_cgroup=True, cgroup_root=cgroup_root)

        self.assertEqual(8 * 1024**3, result["total"])
        self.assertEqual(1024**3, result["used"])
        self.assertEqual(2 * 1024**3, result["swap_total"])
        self.assertEqual(512 * 1024**2, result["swap_used"])

    def test_host_memory_ignores_container_cgroup_limit(self):
        from asr_service.services.system_monitor import _memory

        kib_per_gib = 1024 * 1024
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            cgroup_root = root / "cgroup"
            proc_root.mkdir()
            cgroup_root.mkdir()
            (proc_root / "meminfo").write_text(
                "\n".join(
                    (
                        f"MemTotal: {116 * kib_per_gib} kB",
                        f"MemAvailable: {109 * kib_per_gib} kB",
                        f"MemFree: {55 * kib_per_gib} kB",
                        f"Cached: {52 * kib_per_gib} kB",
                        "SReclaimable: 0 kB",
                        "Shmem: 0 kB",
                        f"SwapTotal: {8 * kib_per_gib} kB",
                        f"SwapFree: {8 * kib_per_gib} kB",
                    )
                )
            )
            (cgroup_root / "memory.max").write_text(str(32 * 1024**3))
            (cgroup_root / "memory.current").write_text(str(16 * 1024**3))
            (cgroup_root / "memory.stat").write_text("inactive_file 0\n")

            host = _memory(proc_root, use_cgroup=False, cgroup_root=cgroup_root)
            container = _memory(
                proc_root, use_cgroup=True, cgroup_root=cgroup_root
            )

        self.assertEqual(host["total"], 116 * 1024**3)
        self.assertEqual(host["used"], 7 * 1024**3)
        self.assertEqual(host["percent"], 6.0)
        self.assertEqual(container["total"], 32 * 1024**3)
        self.assertEqual(container["percent"], 50.0)

    def test_host_storage_uses_read_only_root_filesystem_probe(self):
        from asr_service.services.system_monitor import _storage_path

        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "rootfs-probe"
            probe.write_text("host")
            with patch.dict(
                "os.environ", {"ASR_HOST_STORAGE_PATH": str(probe)}
            ):
                measured, displayed, scope = _storage_path(None, "host")

        self.assertEqual(measured, probe)
        self.assertEqual(displayed, "/")
        self.assertEqual(scope, "host")


if __name__ == "__main__":
    unittest.main()
