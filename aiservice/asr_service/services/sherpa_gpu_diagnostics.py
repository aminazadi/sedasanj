"""Summarize native worker failures without exposing arbitrary stderr or input."""

import signal

STAGE_PREFIX = "SHERPA_GPU_STAGE="
STAGES = (
    "parent_guard",
    "import_runtime",
    "check_runtime",
    "read_request",
    "load_model",
    "read_audio",
    "accept_waveform",
    "decode_audio",
    "serialize_result",
)

# Only fixed signatures and messages may cross the native worker boundary.
FAILURES = (
    (
        ("out of memory", "cuda_error_out_of_memory", "cudaerrormemoryallocation"),
        "cuda_out_of_memory",
        "CUDA out of memory; reduce audio length or GPU concurrency",
    ),
    (
        ("invalid device ordinal", "no cuda-capable device", "cuda_error_no_device"),
        "device_unavailable",
        "Check the leased GPU UUID and container GPU visibility",
    ),
    (
        ("cuda driver version is insufficient", "cuda_error_insufficient_driver"),
        "driver_incompatible",
        "Check the NVIDIA driver against the installed CUDA runtime",
    ),
    (
        ("error while loading shared libraries", "cannot open shared object file"),
        "library_load_failed",
        "Check CUDA/cuDNN library dependencies in the GPU image",
    ),
    (("cudnn_status_",), "cudnn_failure", "Check cuDNN compatibility and audio length"),
    (
        ("cublas_status_",),
        "cublas_failure",
        "Check cuBLAS compatibility and GPU memory",
    ),
    (
        ("invalid device function", "no kernel image is available"),
        "kernel_incompatible",
        "Check runtime support for the selected GPU architecture",
    ),
    (
        (
            "invalid protobuf",
            "invalid graph",
            "invalidgraph",
            "invalid model",
            "invalid rank",
            "invalid dimensions",
            "context_size",
            "not_implemented",
            "not implemented",
        ),
        "model_runtime_failure",
        "Verify model files and ONNX operator/runtime compatibility",
    ),
    (
        ("libsndfileerror", "format not recognised", "format not recognized"),
        "audio_read_failed",
        "Verify the task audio is a readable decompressed audio file",
    ),
)


def worker_failure(stderr, returncode=None, *, reason=None):
    """Return bounded, allowlisted diagnostics suitable for persisted task errors."""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    stderr = stderr or ""
    stage = "unknown"
    for line in stderr.splitlines():
        if line.startswith(STAGE_PREFIX) and line[len(STAGE_PREFIX) :] in STAGES:
            stage = line[len(STAGE_PREFIX) :]
    lowered = stderr.lower()
    action = "Compare the original task audio and leased GPU with the successful short-audio probe"
    if reason is None:
        reason = "worker_failed"
        for signatures, category, suggested_action in FAILURES:
            if any(signature in lowered for signature in signatures):
                reason, action = category, suggested_action
                break
        else:
            if "fallback to cpu" in lowered:
                reason = "cpu_fallback"
                action = "Check CUDA provider initialization or select CPU mode in GPU settings"
    elif reason == "timeout":
        action = "Reduce audio length or increase ASR_SHERPA_GPU_TIMEOUT_SECONDS"
    elif reason == "launch_failed":
        action = "Check worker process limits and rebuild the GPU image"
    elif reason == "invalid_result":
        action = "Rebuild the GPU image and retry with the original task audio"
    details = [f"reason={reason}", f"stage={stage}"]
    if returncode is not None:
        details.append(f"exit_code={returncode}")
        if returncode < 0:
            try:
                details.append(f"signal={signal.Signals(-returncode).name}")
            except ValueError:
                pass
    return f"SS-SVC-0001: Sherpa CUDA failed ({'; '.join(details)}). {action}; then submit a new task"
