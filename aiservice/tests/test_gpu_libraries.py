import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "docker" / "configure-gpu-libraries.py"
spec = importlib.util.spec_from_file_location("gpu_libraries", SCRIPT)
gpu_libraries = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu_libraries)


class GpuLibraryTests(unittest.TestCase):
    def test_discovers_wheel_libraries_in_both_python_layouts_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            expected = [
                root / "pure/nvidia/cudnn/lib",
                root / "plat/nvidia/cublas/lib",
                root / "plat/torch/lib",
            ]
            for path in expected:
                path.mkdir(parents=True)
            (root / "pure/nvidia/ignored").mkdir()
            with patch.object(
                gpu_libraries.sysconfig,
                "get_path",
                side_effect=lambda key: str(root / {"purelib": "pure", "platlib": "plat"}[key]),
            ):
                self.assertEqual(gpu_libraries.library_directories(), sorted(expected))
            with patch.object(gpu_libraries.sysconfig, "get_path", return_value=str(root / "plat")):
                self.assertEqual(gpu_libraries.library_directories(), sorted(expected[1:]))

    def test_registers_paths_atomically_before_refreshing_loader_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asr-nvidia.conf"
            destination.write_text("old\n")

            def refresh(command, **kwargs):
                self.assertEqual(destination.read_text(), "/wheels/nvidia/cudnn/lib\n")
                self.assertEqual(command, ["ldconfig"])
                self.assertTrue(kwargs["check"])

            with patch.object(
                gpu_libraries,
                "library_directories",
                return_value=[Path("/wheels/nvidia/cudnn/lib")],
            ), patch.object(gpu_libraries.subprocess, "run", side_effect=refresh):
                gpu_libraries.configure(destination)
            self.assertEqual(list(Path(directory).iterdir()), [destination])
            self.assertEqual(destination.stat().st_mode & 0o777, 0o644)

    def test_missing_wheels_preserve_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asr-nvidia.conf"
            destination.write_text("old\n")
            with patch.object(gpu_libraries, "library_directories", return_value=[]), patch.object(
                gpu_libraries.subprocess, "run"
            ) as run:
                with self.assertRaisesRegex(RuntimeError, "Dockerfile.gpu"):
                    gpu_libraries.configure(destination)
                run.assert_not_called()
            self.assertEqual(destination.read_text(), "old\n")

    def test_check_loads_cudnn_ops_and_required_symbols_without_torch(self):
        libraries = {name: Mock(spec=[symbol]) for name, symbol in gpu_libraries.LIBRARIES.items()}
        with patch.object(gpu_libraries.ctypes, "CDLL", side_effect=libraries.__getitem__) as load:
            gpu_libraries.check_libraries()
        self.assertEqual([call.args[0] for call in load.call_args_list], list(libraries))
        libraries["libcudnn_ops.so.9"] = Mock(spec=[])
        with patch.object(gpu_libraries.ctypes, "CDLL", side_effect=libraries.__getitem__):
            with self.assertRaises(AttributeError):
                gpu_libraries.check_libraries()

    def test_missing_native_library_reports_actionable_code(self):
        output = io.StringIO()
        with patch.object(gpu_libraries.sys, "argv", [str(SCRIPT), "--check"]), patch.object(
            gpu_libraries.ctypes, "CDLL", side_effect=OSError("libcudnn_ops.so.9 not found")
        ), contextlib.redirect_stderr(output):
            self.assertEqual(gpu_libraries.main(), 1)
        self.assertIn("SS-DEP-0001", output.getvalue())
        self.assertIn("Rebuild Dockerfile.gpu", output.getvalue())

    def test_build_checks_libraries_in_fresh_interpreter_after_configuring(self):
        with patch.object(gpu_libraries.sys, "argv", [str(SCRIPT)]), patch.object(
            gpu_libraries, "configure"
        ) as configure, patch.object(gpu_libraries.subprocess, "run") as run:
            self.assertEqual(gpu_libraries.main(), 0)
            configure.assert_called_once_with()
            run.assert_called_once_with(
                [gpu_libraries.sys.executable, str(SCRIPT), "--check"], check=True
            )
            run.side_effect = subprocess.CalledProcessError(1, "check")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gpu_libraries.main(), 1)
