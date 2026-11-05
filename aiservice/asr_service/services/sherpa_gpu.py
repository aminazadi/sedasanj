"""Run NeMo CTC/RNNT with Sherpa CUDA in a process scoped to one leased GPU."""

import json
import os
import subprocess
import sys
from pathlib import Path

from .sherpa_gpu_diagnostics import STAGE_PREFIX, worker_failure


class SherpaGpuError(RuntimeError):
    pass


RNNT_GPU_FILES = ("encoder.onnx", "decoder.onnx", "joiner.onnx")


def rnnt_gpu_artifacts_ready(root):
    try:
        return all(
            (Path(root) / name).is_file() and (Path(root) / name).stat().st_size > 0
            for name in RNNT_GPU_FILES
        )
    except OSError:
        return False


class SherpaGpuModel:
    def __init__(self, root, device, threads, architecture="nemoCtc"):
        self.root = str(root)
        self.device = str(device)
        self.threads = threads
        self.architecture = architecture

    def transcribe(self, path):
        if self.architecture == "transducer" and not rnnt_gpu_artifacts_ready(
            self.root
        ):
            raise SherpaGpuError(
                "SS-DEP-0002: RNNT CUDA requires FP32 encoder/decoder/joiner ONNX files; "
                "use Complete GPU files on the model card, then submit a new task"
            )
        # Sherpa's Python CUDA provider targets device 0. Remap only this child;
        # never mutate the API process environment while other GPUs are active.
        environment = {**os.environ, "CUDA_VISIBLE_DEVICES": self.device}
        payload = {
            "root": self.root,
            "path": str(Path(path).resolve()),
            "threads": self.threads,
            "architecture": self.architecture,
        }
        try:
            result = subprocess.run(
                [sys.executable, "-m", "asr_service.services.sherpa_gpu"],
                input=json.dumps(payload),
                capture_output=True,
                check=False,
                text=True,
                env=environment,
                timeout=max(1, int(os.getenv("ASR_SHERPA_GPU_TIMEOUT_SECONDS", "900"))),
            )
        except subprocess.TimeoutExpired as exc:
            raise SherpaGpuError(worker_failure(exc.stderr, reason="timeout")) from None
        except (OSError, ValueError):
            raise SherpaGpuError(worker_failure("", reason="launch_failed")) from None
        if result.returncode or "fallback to cpu" in result.stderr.lower():
            raise SherpaGpuError(worker_failure(result.stderr, result.returncode))
        try:
            data = json.loads(result.stdout)
            if not isinstance(data["text"], str) or not isinstance(
                data["duration"], (int, float)
            ):
                raise TypeError("Invalid worker result")
            return data["text"], data["duration"]
        except (ValueError, TypeError, KeyError):
            raise SherpaGpuError(
                worker_failure(
                    result.stderr, result.returncode, reason="invalid_result"
                )
            ) from None


def main():
    def stage(name):
        print(f"{STAGE_PREFIX}{name}", file=sys.stderr, flush=True)

    stage("parent_guard")
    # Match the chat worker's lifetime to its parent on Linux.
    if sys.platform == "linux":
        import ctypes
        import signal

        parent = os.getppid()
        if (
            ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0
            or os.getppid() != parent
        ):
            return 1
    stage("import_runtime")
    import sherpa_onnx
    import soundfile as sf

    stage("check_runtime")
    if "+cuda12.cudnn9" not in sherpa_onnx.__version__:
        return 1
    stage("read_request")
    payload = json.load(sys.stdin)
    root = Path(payload["root"])
    options = {
        "tokens": str(root / "tokens.txt"),
        "num_threads": payload["threads"],
        "provider": "cuda",
    }
    stage("load_model")
    if payload.get("architecture", "nemoCtc") == "transducer":
        recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(root / "encoder.onnx"),
            decoder=str(root / "decoder.onnx"),
            joiner=str(root / "joiner.onnx"),
            model_type="nemo_transducer",
            **options,
        )
    else:
        recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
            model=str(root / "model.onnx"), **options
        )
    stage("read_audio")
    audio, sample_rate = sf.read(payload["path"], dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    stream = recognizer.create_stream()
    stage("accept_waveform")
    stream.accept_waveform(sample_rate, audio)
    stage("decode_audio")
    recognizer.decode_stream(stream)
    stage("serialize_result")
    json.dump(
        {"text": stream.result.text, "duration": len(audio) / sample_rate}, sys.stdout
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
