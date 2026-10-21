import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asr_service.services import gpu_runtime


class GpuRuntimeTests(unittest.TestCase):
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
                model_file.truncate(5 * 1024**3)
            with patch.object(gpu_runtime, "enabled_devices", return_value=devices), patch.object(
                gpu_runtime, "get_settings", return_value=settings
            ), patch.object(storage, "MODEL_DIR", Path(directory)):
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
            ), patch.object(storage, "MODEL_DIR", Path(directory)):
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


if __name__ == "__main__":
    unittest.main()
