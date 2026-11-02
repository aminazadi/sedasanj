import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asr_service.services import gpu_runtime, inference, sherpa_gpu


class SherpaGpuTests(unittest.TestCase):
    def test_cuda_wheel_and_working_torch_cuda_are_both_required(self):
        for wheel, cuda, expected in (
            ("1.12.39", True, False),
            ("1.12.39+cuda12.cudnn9", False, False),
            ("1.12.39+cuda12.cudnn9", True, True),
        ):
            with self.subTest(wheel=wheel, cuda=cuda), patch.dict(
                sys.modules,
                {
                    "torch": Mock(cuda=Mock(is_available=Mock(return_value=cuda))),
                    "ctranslate2": Mock(get_cuda_device_count=Mock(return_value=0)),
                    "llama_cpp": Mock(llama_supports_gpu_offload=Mock(return_value=False)),
                },
            ), patch.object(gpu_runtime, "version", return_value=wheel), patch.dict(
                gpu_runtime._capability_cache, {"at": 0.0, "value": {}}
            ):
                self.assertEqual(gpu_runtime.runtime_capabilities()["sherpa_onnx"], expected)

    def tearDown(self):
        inference._load.cache_clear()

    def test_shenava_eligibility_depends_on_sherpa_not_whisper(self):
        with patch.object(
            gpu_runtime, "enabled_devices", return_value=[{"uuid": "GPU-b"}]
        ), patch.object(
            gpu_runtime,
            "runtime_capabilities",
            return_value={"sherpa_onnx": True, "ctranslate2": False},
        ):
            for model in ("shenava-koochik", "shenava-rizeh", "shenava-rizeh-pizeh"):
                self.assertTrue(gpu_runtime.gpu_eligible("asr", model))
            self.assertFalse(gpu_runtime.gpu_eligible("asr", "whisper-persian-v4"))
            self.assertFalse(gpu_runtime.gpu_eligible("asr", "shenava-koochik-v1-5-rnnt"))
        with patch.object(gpu_runtime, "enabled_devices", return_value=[]):
            self.assertFalse(gpu_runtime.gpu_eligible("asr", "shenava-koochik"))

    def test_cpu_loader_still_uses_sherpa_and_gpu_loader_is_isolated(self):
        sherpa = Mock()
        with patch.dict(sys.modules, {"sherpa_onnx": sherpa}), patch.object(
            gpu_runtime, "current_device", return_value={"uuid": "GPU-b"}
        ):
            inference._load("shenava-koochik", None)
            self.assertNotIn("provider", sherpa.OfflineRecognizer.from_nemo_ctc.call_args.kwargs)
            model = inference._load("shenava-koochik", 1)
            self.assertIsInstance(model, sherpa_gpu.SherpaGpuModel)
            self.assertEqual(model.device, "GPU-b")
            sherpa.OfflineRecognizer.from_nemo_ctc.assert_called_once()

    def test_each_worker_receives_its_leased_gpu_without_changing_parent_environment(self):
        completed = SimpleNamespace(
            returncode=0, stdout='{"text":"speech","duration":2.5}', stderr=""
        )
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "parent"}), patch.object(
            sherpa_gpu.subprocess, "run", return_value=completed
        ) as run:
            for gpu in ("GPU-a", "GPU-b"):
                result = sherpa_gpu.SherpaGpuModel(Path("/models/shenava"), gpu, 2).transcribe(
                    "audio.wav"
                )
                self.assertEqual(result, ("speech", 2.5))
                self.assertEqual(run.call_args.kwargs["env"]["CUDA_VISIBLE_DEVICES"], gpu)
                self.assertEqual(json.loads(run.call_args.kwargs["input"])["threads"], 2)
                self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "parent")

    def test_crash_timeout_invalid_result_and_cpu_fallback_are_coded_failures(self):
        model = sherpa_gpu.SherpaGpuModel(Path("/models/shenava"), "GPU-a", 2)
        cases = [
            SimpleNamespace(returncode=-6, stdout="", stderr="native crash"),
            SimpleNamespace(
                returncode=0, stdout='{"text":"ok","duration":1}', stderr="Fallback to cpu!"
            ),
            SimpleNamespace(returncode=0, stdout="{}", stderr=""),
            SimpleNamespace(returncode=0, stdout="not json", stderr=""),
        ]
        for result in cases:
            with self.subTest(result=result), patch.object(
                sherpa_gpu.subprocess, "run", return_value=result
            ):
                with self.assertRaisesRegex(sherpa_gpu.SherpaGpuError, "SS-SVC-0001"):
                    model.transcribe("audio.wav")
        with patch.object(
            sherpa_gpu.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 1)
        ):
            with self.assertRaisesRegex(sherpa_gpu.SherpaGpuError, "SS-SVC-0001"):
                model.transcribe("audio.wav")

    def test_child_explicitly_selects_cuda_and_preserves_audio_duration(self):
        audio = Mock()
        samples = Mock()
        samples.__len__ = Mock(return_value=32000)
        audio.mean.return_value = samples
        soundfile = Mock()
        soundfile.read.return_value = (audio, 16000)
        sherpa = Mock(__version__="1.12.39+cuda12.cudnn9")
        recognizer = sherpa.OfflineRecognizer.from_nemo_ctc.return_value
        recognizer.create_stream.return_value.result.text = "speech"
        output = io.StringIO()
        payload = io.StringIO(
            json.dumps({"root": "/models/shenava", "path": "/audio.wav", "threads": 2})
        )
        with patch.dict(sys.modules, {"sherpa_onnx": sherpa, "soundfile": soundfile}), patch.object(
            sys, "platform", "darwin"
        ), patch.object(sys, "stdin", payload), contextlib.redirect_stdout(output):
            self.assertEqual(sherpa_gpu.main(), 0)
        self.assertEqual(
            sherpa.OfflineRecognizer.from_nemo_ctc.call_args.kwargs["provider"], "cuda"
        )
        self.assertEqual(json.loads(output.getvalue()), {"text": "speech", "duration": 2.0})

    def test_gpu_transcription_uses_child_result_and_normalizes_text(self):
        model = Mock()
        model.transcribe.return_value = ("ي ك", 2.5)
        with patch.object(inference, "load", return_value=model), patch.object(
            gpu_runtime, "current_device_index", return_value=1
        ), patch.object(inference.os.path, "isfile", return_value=True):
            text, segments, duration, _ = inference.transcribe(
                "audio.wav", "shenava-koochik", 2, True, None
            )
        self.assertEqual(text, "ی ک")
        self.assertEqual(duration, 2.5)
        self.assertEqual(segments[0]["end"], 2.5)
