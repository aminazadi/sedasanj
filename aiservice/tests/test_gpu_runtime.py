import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asr_service.services import gpu_runtime


class GpuRuntimeTests(unittest.TestCase):
    def test_live_gpu_compute_and_memory_are_independent_and_optional_metrics_can_be_unavailable(self):
        process = SimpleNamespace(stdout="0, GPU-a, RTX 3060, 12288, 8192, 0, 42, 25.5, 170, [N/A]\n")
        with patch.object(gpu_runtime.subprocess, "run", return_value=process):
            gpu_runtime._device_cache["at"] = 0
            device = gpu_runtime.discover_gpus()[0]
        self.assertEqual(device["utilization_percent"], 0)
        self.assertEqual(device["memory_total"] - device["memory_free"], 4096 * 1024**2)
        self.assertEqual(device["power_watts"], 25.5)
        self.assertEqual(device["temperature_celsius"], 42)
        self.assertIsNone(device["fan_percent"])
        self.assertGreater(device["sampled_at"], 0)

    def test_discovers_stable_uuid_and_memory_values(self):
        process = SimpleNamespace(stdout="0, GPU-a, RTX 3060, 12288, 8192, 17\n")
        with patch.object(gpu_runtime.subprocess, "run", return_value=process):
            gpu_runtime._device_cache["at"] = 0
            devices = gpu_runtime.discover_gpus()
        self.assertEqual(devices[0]["uuid"], "GPU-a")
        self.assertEqual(devices[0]["memory_total"], 12288 * 1024 * 1024)
        self.assertEqual(devices[0]["memory_free"], 8192 * 1024 * 1024)

    def test_missing_nvidia_smi_reports_no_visible_devices(self):
        with patch.object(gpu_runtime.subprocess, "run", side_effect=FileNotFoundError):
            gpu_runtime._device_cache["at"] = 0
            self.assertEqual(gpu_runtime.discover_gpus(), [])

    def test_transient_nvidia_smi_failure_keeps_last_good_devices(self):
        good = SimpleNamespace(stdout="0, GPU-a, RTX 3060, 12288, 8192, 17\n")
        with patch.object(gpu_runtime.subprocess, "run", return_value=good):
            gpu_runtime._device_cache["at"] = 0
            gpu_runtime.discover_gpus()
        failure = gpu_runtime.subprocess.TimeoutExpired("nvidia-smi", 3)
        with patch.object(gpu_runtime.subprocess, "run", side_effect=failure):
            gpu_runtime._device_cache["at"] = 0
            self.assertEqual(["GPU-a"], [item["uuid"] for item in gpu_runtime.discover_gpus()])

    def test_repeated_device_failures_quarantine_a_gpu_until_it_succeeds(self):
        device = {"index": 0, "uuid": "GPU-q", "memory_free": 8 * 1024**3}
        settings = {"mode": "auto", "enabled_devices": ["GPU-q"], "max_concurrent_per_device": 1, "min_free_vram_mb": 1024}
        with patch.object(gpu_runtime, "get_settings", return_value=settings), patch.object(
            gpu_runtime, "discover_gpus", return_value=[device]
        ):
            for _ in range(gpu_runtime.QUARANTINE_THRESHOLD):
                gpu_runtime.record_error("GPU-q", "CUDA error: illegal memory access")
            self.assertTrue(gpu_runtime.is_quarantined("GPU-q"))
            with self.assertRaises(TimeoutError):
                with gpu_runtime.reserve(device):
                    pass
            gpu_runtime._quarantine_until["GPU-q"] = 0
            with gpu_runtime.reserve(device):
                pass
            gpu_runtime.record_success("GPU-q")
            self.assertEqual(0, gpu_runtime._quarantine_levels.get("GPU-q", 0))

    def test_out_of_memory_and_task_errors_never_quarantine(self):
        for _ in range(gpu_runtime.QUARANTINE_THRESHOLD + 1):
            gpu_runtime.record_error("GPU-o", "CUDA out of memory")
            gpu_runtime.record_error("GPU-o", "ValueError: bad audio")
        self.assertFalse(gpu_runtime.is_quarantined("GPU-o"))

    def test_reservation_is_per_device_and_sets_model_device_context(self):
        device = {"index": 1, "uuid": "GPU-b", "memory_free": 8 * 1024**3}
        settings = {
            "mode": "auto",
            "enabled_devices": [device["uuid"]],
            "max_concurrent_per_device": 1,
            "min_free_vram_mb": 1024,
        }
        with patch.object(gpu_runtime, "get_settings", return_value=settings), patch.object(
            gpu_runtime, "discover_gpus", return_value=[device]
        ), patch.dict("os.environ", {}, clear=False):
            with gpu_runtime.reserve(device):
                self.assertEqual(gpu_runtime.current_device_index(), 1)
                with self.assertRaises(TimeoutError):
                    with gpu_runtime.reserve(device):
                        pass
            self.assertIsNone(gpu_runtime.current_device_index())

    def test_group_reservation_frees_idle_resident_models_when_vram_is_short(self):
        gib = 1024**3
        state = {"free": 5 * gib}
        devices = lambda: [
            {"index": 0, "uuid": "GPU-a", "memory_free": state["free"]},
            {"index": 1, "uuid": "GPU-b", "memory_free": state["free"]},
        ]
        settings = {
            "mode": "auto", "enabled_devices": ["GPU-a", "GPU-b"],
            "max_concurrent_per_device": 1, "min_free_vram_mb": 1024,
        }

        def release(index):
            state["free"] = 11 * gib  # the idle split context was closed
            return 1

        with patch.object(gpu_runtime, "get_settings", return_value=settings), patch.object(
            gpu_runtime, "discover_gpus", side_effect=lambda: devices()
        ), patch.object(gpu_runtime.gpu_memory, "evict_idle", side_effect=release) as evict:
            with gpu_runtime.reserve_group(devices(), timeout=0, required_bytes=14 * gib) as context:
                self.assertTrue(context["split"])
        self.assertEqual(2, evict.call_count)

    def test_group_reservation_still_times_out_when_eviction_frees_nothing(self):
        gib = 1024**3
        devices = [
            {"index": 0, "uuid": "GPU-a", "memory_free": 5 * gib},
            {"index": 1, "uuid": "GPU-b", "memory_free": 5 * gib},
        ]
        settings = {
            "mode": "auto", "enabled_devices": ["GPU-a", "GPU-b"],
            "max_concurrent_per_device": 1, "min_free_vram_mb": 1024,
        }
        with patch.object(gpu_runtime, "get_settings", return_value=settings), patch.object(
            gpu_runtime, "discover_gpus", return_value=devices
        ), patch.object(gpu_runtime.gpu_memory, "evict_idle", return_value=0):
            with self.assertRaises(TimeoutError):
                with gpu_runtime.reserve_group(devices, timeout=0, required_bytes=14 * gib):
                    pass

    def test_cuda_runtime_gates_gpu_eligibility(self):
        device = {"index": 0, "uuid": "GPU-a", "memory_free": 8 * 1024**3}
        with patch.object(gpu_runtime, "enabled_devices", return_value=[device]), patch.object(
            gpu_runtime, "runtime_capabilities", return_value={"ctranslate2": False, "llama_cpp": False, "torch": False}
        ):
            self.assertFalse(gpu_runtime.gpu_eligible("asr", "whisper-large-v3"))
            self.assertFalse(gpu_runtime.gpu_eligible("chat", "dorna-8b-q4_k_m"))

    def test_multi_gpu_reservation_is_atomic_and_marks_split_context(self):
        devices = [
            {"index": 0, "uuid": "GPU-a", "memory_free": 8 * 1024**3},
            {"index": 1, "uuid": "GPU-b", "memory_free": 8 * 1024**3},
        ]
        settings = {
            "mode": "auto",
            "enabled_devices": [device["uuid"] for device in devices],
            "max_concurrent_per_device": 1,
            "min_free_vram_mb": 1024,
        }
        with patch.object(gpu_runtime, "get_settings", return_value=settings), patch.object(
            gpu_runtime, "discover_gpus", return_value=devices
        ):
            with gpu_runtime.reserve_group(devices):
                self.assertTrue(gpu_runtime.current_is_split())
                self.assertEqual(gpu_runtime.current_device_indices(), [0, 1])
                with self.assertRaises(TimeoutError):
                    with gpu_runtime.reserve(devices[0]):
                        pass
            self.assertIsNone(gpu_runtime.current_device())

    def test_oversized_gguf_requests_group_only_when_combined_vram_can_fit(self):
        from asr_service.infrastructure import storage

        devices = [
            {"index": 0, "uuid": "GPU-a", "memory_total": 8 * 1024**3, "memory_free": 4 * 1024**3},
            {"index": 1, "uuid": "GPU-b", "memory_total": 8 * 1024**3, "memory_free": 4 * 1024**3},
        ]
        settings = {"min_free_vram_mb": 1024}
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory) / "dorna-8b-q4_k_m"
            model_dir.mkdir()
            with (model_dir / "Dorna-Llama3-8B-Instruct.Q4_K_M.gguf").open("wb") as model_file:
                model_file.truncate(4 * 1024**3)
            with patch.object(gpu_runtime, "enabled_devices", return_value=devices), patch.object(
                gpu_runtime, "get_settings", return_value=settings
            ), patch.object(gpu_runtime, "llm_context_size", return_value=2048), patch.object(
                storage, "MODEL_DIR", Path(directory)
            ):
                self.assertFalse(gpu_runtime.requires_multi_gpu("chat", "dorna-8b-q4_k_m"))
                devices[0]["memory_total"] = 6 * 1024**3
                devices[1]["memory_total"] = 6 * 1024**3
                self.assertTrue(gpu_runtime.requires_multi_gpu("chat", "dorna-8b-q4_k_m"))

    def test_split_selects_only_the_cards_required_for_the_model(self):
        from asr_service.infrastructure import storage

        devices = [
            {"index": index, "uuid": f"GPU-{index}", "memory_total": 6 * 1024**3, "memory_free": 5 * 1024**3}
            for index in range(3)
        ]
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory) / "dorna-8b-q4_k_m"
            model_dir.mkdir()
            with (model_dir / "Dorna-Llama3-8B-Instruct.Q4_K_M.gguf").open("wb") as model_file:
                model_file.truncate(6 * 1024**3)
            with patch.object(gpu_runtime, "enabled_devices", return_value=devices), patch.object(
                gpu_runtime, "get_settings", return_value={"min_free_vram_mb": 1024}
            ), patch.object(gpu_runtime, "llm_context_size", return_value=2048), patch.object(
                storage, "MODEL_DIR", Path(directory)
            ):
                self.assertEqual(2, len(gpu_runtime.split_devices("chat", "dorna-8b-q4_k_m")))

    def test_cpu_mode_preserves_selected_devices_for_admin_settings(self):
        device = {"index": 0, "uuid": "GPU-a", "name": "RTX", "memory_total": 8 * 1024**3,
                  "memory_free": 7 * 1024**3, "utilization_percent": 0}
        settings = {"mode": "cpu", "enabled_devices": ["GPU-a"], "max_concurrent_per_device": 1,
                    "cpu_fallback_seconds": 30, "min_free_vram_mb": 1024}
        with patch.object(gpu_runtime, "get_settings", return_value=settings), patch.object(
            gpu_runtime, "discover_gpus", return_value=[device]
        ), patch.object(gpu_runtime, "runtime_capabilities", return_value={}), patch.object(
            gpu_runtime, "rows", return_value=[]
        ):
            observed = gpu_runtime.snapshot()["devices"][0]
        self.assertTrue(observed["selected"])
        self.assertFalse(observed["enabled"])

    def test_memory_estimate_includes_kv_cache_and_compute_buffers(self):
        import tempfile
        from asr_service.domain.catalog import CATALOG, ModelFile, ModelSpec
        from asr_service.infrastructure import storage

        spec = ModelSpec("gemma-test", "llm", "Gemma", "", "", "gguf",
                         files=(ModelFile("g.gguf", "", 2489757856),))
        with tempfile.TemporaryDirectory() as directory, patch.dict(CATALOG, {"gemma-test": spec}), patch.object(
            storage, "MODEL_DIR", Path(directory)
        ):
            small = gpu_runtime.model_memory_estimate("gemma-test", 4096)
            large = gpu_runtime.model_memory_estimate("gemma-test", 12288)
        self.assertGreater(large, small)
        # 12288 tokens on one GPU must not fit GPU1's measured 4493 MiB free.
        self.assertGreater(large, 4493 * 1024**2)

    def test_device_has_room_rejects_a_gpu_that_cannot_hold_the_context(self):
        device = {"index": 1, "uuid": "GPU-b", "memory_free": 4493 * 1024**2}
        with patch.object(gpu_runtime, "discover_gpus", return_value=[device]), patch.object(
            gpu_runtime, "model_memory_estimate", return_value=5 * 1024**3
        ), patch("asr_service.services.text_processing.has_resident_context", return_value=False):
            self.assertFalse(gpu_runtime.device_has_room("GPU-b", "chat", "gemma-test"))
            self.assertTrue(gpu_runtime.device_has_room("GPU-b", "asr", "gemma-test"))
        with patch.object(gpu_runtime, "discover_gpus", return_value=[device]), patch.object(
            gpu_runtime, "model_memory_estimate", return_value=5 * 1024**3
        ), patch("asr_service.services.text_processing.has_resident_context", return_value=True):
            self.assertTrue(gpu_runtime.device_has_room("GPU-b", "chat", "gemma-test"))

    def test_llama_context_failure_counts_as_resource_failure(self):
        self.assertTrue(gpu_runtime.is_resource_failure("ValueError: Failed to create llama_context"))
        self.assertTrue(gpu_runtime.is_resource_failure("CUDA error: out of memory"))
        self.assertFalse(gpu_runtime.is_resource_failure("file not found"))


if __name__ == "__main__":
    unittest.main()


class GpuCapacityTests(unittest.TestCase):
    def setUp(self):
        gpu_runtime._effective_limits.clear()
        gpu_runtime._oom_split_models.clear()
        gpu_runtime._success_streaks.clear()

    def tearDown(self):
        self.setUp()

    def test_effective_limit_starts_at_the_configured_capacity_and_backs_off_on_oom(self):
        settings = {"max_concurrent_per_device": 4}
        with patch.object(gpu_runtime, "get_settings", return_value=settings):
            gpu_runtime.record_error("GPU-a", "CUDA out of memory")
            self.assertEqual(gpu_runtime._effective_limits["GPU-a"], 3)
            for _ in range(10):
                gpu_runtime.record_success("GPU-a")
            self.assertEqual(gpu_runtime._effective_limits["GPU-a"], 4)

    def test_oom_forced_split_expires_instead_of_lasting_until_restart(self):
        gpu_runtime.note_model_oom("m", "CUDA out of memory")
        self.assertIn("m", gpu_runtime._oom_split_models)
        gpu_runtime._oom_split_models["m"] -= gpu_runtime.OOM_SPLIT_TTL_SECONDS + 1
        devices = [
            {"uuid": f"GPU-{i}", "memory_total": 8 * 1024**3, "memory_free": 8 * 1024**3, "index": i}
            for i in range(2)
        ]
        with (
            patch.object(gpu_runtime, "enabled_devices", return_value=devices),
            patch.object(gpu_runtime, "model_memory_estimate", return_value=1024**3),
            patch.object(gpu_runtime, "get_settings", return_value={"min_free_vram_mb": 0}),
        ):
            self.assertEqual(gpu_runtime.split_devices("chat", "m"), [])
        self.assertNotIn("m", gpu_runtime._oom_split_models)
