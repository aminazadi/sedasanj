"""Run NeMo CTC with Sherpa CUDA in a process scoped to one leased GPU."""

import json
import os
from pathlib import Path
import subprocess
import sys


class SherpaGpuError(RuntimeError):
    pass


class SherpaGpuModel:
    def __init__(self, root, device, threads):
        self.root = str(root)
        self.device = str(device)
        self.threads = threads

    def transcribe(self, path):
        # Sherpa's Python CUDA provider targets device 0. Remap only this child;
        # never mutate the API process environment while other GPUs are active.
        environment = {**os.environ, "CUDA_VISIBLE_DEVICES": self.device}
        payload = {"root": self.root, "path": str(Path(path).resolve()), "threads": self.threads}
        try:
            result = subprocess.run(
                [sys.executable, "-m", "asr_service.services.sherpa_gpu"],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=environment,
                timeout=max(1, int(os.getenv("ASR_SHERPA_GPU_TIMEOUT_SECONDS", "900"))),
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise SherpaGpuError(
                "SS-SVC-0001: Sherpa CUDA worker stopped or timed out; check GPU memory, "
                "rebuild the GPU image, or select CPU mode in GPU settings"
            ) from exc
        if result.returncode or "fallback to cpu" in result.stderr.lower():
            raise SherpaGpuError(
                "SS-SVC-0001: Sherpa CUDA inference failed; check CUDA/cuDNN libraries "
                "and GPU memory, or select CPU mode in GPU settings"
            )
        try:
            data = json.loads(result.stdout)
            if not isinstance(data["text"], str) or not isinstance(data["duration"], (int, float)):
                raise ValueError("Invalid worker result")
            return data["text"], data["duration"]
        except (ValueError, TypeError, KeyError) as exc:
            raise SherpaGpuError(
                "SS-SVC-0001: Invalid Sherpa CUDA worker result; rebuild the GPU image "
                "or select CPU mode in GPU settings"
            ) from exc


def main():
    # Match the chat worker's lifetime to its parent on Linux.
    if sys.platform == "linux":
        import ctypes
        import signal

        parent = os.getppid()
        if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
            return 1
    import sherpa_onnx
    import soundfile as sf

    if "+cuda12.cudnn9" not in sherpa_onnx.__version__:
        return 1
    payload = json.load(sys.stdin)
    root = Path(payload["root"])
    recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
        model=str(root / "model.onnx"),
        tokens=str(root / "tokens.txt"),
        num_threads=payload["threads"],
        provider="cuda",
    )
    audio, sample_rate = sf.read(payload["path"], dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate, audio)
    recognizer.decode_stream(stream)
    json.dump({"text": stream.result.text, "duration": len(audio) / sample_rate}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
