# Changelog

## 2026-11-14 — AMINAZADI

- Added queue wake-ups and a read-only idle precheck: `enqueue` wakes idle workers immediately and an empty poll no longer takes the SQLite write lock.
- Changed the default `ASR_QUEUE_LIMIT` from 100 to 1000 (compose included) and added `ASR_QUEUE_PER_KEY_LIMIT` (per-API-key fairness cap, default off) and `ASR_REMOTE_WORKERS` (default 2).
- Changed the per-GPU concurrency to start at the configured `max_concurrent_per_device` and back off on out-of-memory, instead of starting at 1 after every restart; an out-of-memory forced multi-GPU split now expires after `ASR_OOM_SPLIT_TTL_SECONDS` (default 1800).
- Added `ASR_CUDA_COMPUTE_TYPE` for faster-whisper on CUDA (defaults to `ASR_COMPUTE_TYPE`, so behaviour is unchanged until set; lab confirmation needed).
- Added graceful drain on shutdown (`ASR_DRAIN_SECONDS`), `draining`, `oldest_waiting_seconds` and `quarantined_gpus` on `/ready`, and an administrator-only `GET /metrics` (queue depth, oldest waiting age, GPU quarantine/active).
- Fixed GPU-only (`mode=gpu`) tasks failing instantly with `gpu_unavailable` when `nvidia-smi` hiccuped or no compatible GPU was free: they now stay queued and fail only after `ASR_GPU_UNAVAILABLE_TTL_SECONDS` (default 21600). A transient `nvidia-smi` timeout keeps the last good device list for `ASR_GPU_DISCOVERY_GRACE_SECONDS` (default 30) instead of reporting "no GPU".
- Fixed capacity and infrastructure failures consuming task attempts: out-of-memory and GPU/driver failures requeue with backoff without using an attempt (bounded by `ASR_CAPACITY_MAX_REQUEUES`, default 30, and `ASR_CAPACITY_REQUEUE_MAX_SECONDS`, default 86400), and a restart or expired heartbeat returns the attempt (bounded by `ASR_TASK_MAX_INTERRUPTIONS`, default 5, so a task that keeps killing its worker still ends).
- Added a per-GPU circuit breaker: `ASR_GPU_QUARANTINE_THRESHOLD` (default 3) consecutive device-level failures take a GPU out of rotation for an exponentially growing cool-down (`ASR_GPU_QUARANTINE_BASE_SECONDS` 30 up to `ASR_GPU_QUARANTINE_MAX_SECONDS` 900); one success closes it. A broken card no longer burns the attempts of the whole queue. Quarantine state is shown in the GPU snapshot.
- Fixed stale-run recovery and result expiry running only on worker `cpu-0` (and so stalling behind a long job): they now run on a dedicated maintenance thread. The heartbeat thread survives transient SQLite errors instead of dying silently and letting a healthy run be executed twice.
- Fixed GPU workers being created only at boot: a supervisor thread (`ASR_GPU_SUPERVISOR_SECONDS`, default 15) starts workers for a GPU that appears or returns later.
- Fixed synchronous `/v1/chat/completions` keeping a queued/running task alive after the client disconnected: the task is now cancelled. (A 504 timeout still leaves the task running so it can be fetched from the `Location` header.)
- Added exact token accounting: every chat, text and asynchronous chat task records the input/output/total tokens the model reported (local llama.cpp or 9Router; `input_tokens`/`output_tokens` accepted) on the run and history rows and returns them as `usage` on `GET /v1/tasks/{id}`. Counts are never estimated — `source` is `unavailable` when the model reported nothing. The fake SSE stream now ends with a usage chunk.

## 2026-11-11 — AMINAZADI

- Released VRAM when the GPU is idle: every second the service checks, and after `ASR_GPU_IDLE_UNLOAD_SECONDS` (default 5, 0 disables) without GPU work all idle resident models (Whisper, GGUF, embedding, decision) are unloaded from every GPU. The next request reloads its model, which costs a few seconds.
- Fixed deleting one ASR model dropping every cached ASR engine (all models reloaded afterwards) and two threads loading the same model concurrently (double VRAM): the ASR model cache now evicts only the target model and builds each model once.
- Added a GPU memory manager: PyTorch caches are returned to the driver after `ASR_GPU_IDLE_TRIM_SECONDS` (default 10) of GPU inactivity, never after each request, and idle resident GGUF/embedding/decision models on a GPU are released when another job does not fit, so a resident model no longer causes OOM for the next job. Models in use are never touched; set `ASR_GPU_MEMORY_MANAGER=0` to disable.
- Fixed multi-GPU (split) tasks such as Gemma 12B on two 12 GB cards staying queued forever while an idle split model from an earlier request still held ~7 GB on each GPU: group reservation now releases idle resident models when VRAM is short, and a split context is released for any of its GPUs.

## 2026-11-08 — AMINAZADI

- Fixed `ValueError: Failed to create llama_context` for large-context models such as Gemma 3 4B: the scheduler now estimates weights, KV cache and compute buffers and skips a GPU that cannot hold them (an idle resident context still counts as fitting), and the model loader retries with half the context and then on CPU before failing with a typed `ModelContextError`.
- Treated `Failed to create llama_context` as a resource failure for GPU error accounting and multi-GPU split, logged free VRAM and `n_ctx` per failed attempt, and kept stderr of failed chat subprocesses in the service log.

## 2026-11-04 — AMINAZADI

- Fixed GPU-only tasks that stayed queued with no compatible GPU and kept CPU queue workers alive across transient monitoring failures.
- Added opt-in Silero segmentation for Shenava with streamed VAD frames, per-utterance context and quiet gain, Persian cleanup, deduplication and native span timestamps.
- Scheduled Silero runs through CPU admission, retained model failover for missing artifacts and made silence terminal with a stable error code.

## 2026-11-02 — AMINAZADI

- Raised the decision-model install smoke test timeout from 60s to a configurable 600s (DECISION_SMOKE_TIMEOUT_SECONDS) because loading GLiNER2.5 on a slow CPU exceeded 60s, and reported timeouts with an actionable message.
- Fixed GLiNER2.5 Multi Decide install and runtime loading by using AutoExtractor.from_pretrained instead of the span-only GLiNER2.from_pretrained, which could not load boundary checkpoints and raised ExtractorConfig has no attribute max_width.

## 2026-10-28 — AMINAZADI

- Persisted admin-downloaded AI models in the AISERVICE project-root `models` directory for reuse across deployments.
- Added one-time migration from the legacy data volume and excluded downloaded model artifacts from Git and Docker build contexts.

## 2026-10-22 — AMINAZADI

- Documented NVIDIA Container Toolkit host setup and Docker runtime registration for GPU images that build successfully but cannot start with an NVIDIA device reservation.
- Built llama-cpp-python from source once in the GPU image and verified its CUDA library without importing the package before the host GPU driver is mounted.
- Retried CPU and GPU Python dependency installation through configurable Chinese PyPI mirrors when the primary Iranian mirror returns missing package files.
- Routed GPU image Ubuntu package installation through configurable Iranian and Chinese mirrors with automatic fallback, excluding the blocked NVIDIA apt source from this installation step.
- Completed the environment template for GPU scheduling and operational tuning, and passed GGUF context, queue polling, network metrics, and trusted proxy settings through Compose.
- Removed legacy direct GGUF GPU-layer configuration so CPU fallback cannot bypass GPU reservations.
- Added an optional CUDA 12.6/cuDNN 9 image and Compose overlay for NVIDIA GPU deployments while keeping CPU deployment as the default.
- Added UUID-based GPU discovery, VRAM-aware reservations, per-device model caches, GPU/CPU scheduling, bounded CPU fallback, and OOM-driven concurrency backoff.
- Added administrator GPU mode and device settings, per-GPU runtime metrics, query-preserved settings tabs, and scheduled embedding inference.
- Persisted per-model execution device metadata and added focused GPU runtime coverage.
- Corrected failover dispatch to use the next model run, separated CPU concurrency from GPU reservations, and removed the 100-candidate claim ceiling.
- Stabilized GGUF split decisions against transient free-VRAM changes, reserved only the GPU subset needed by large models, checked available split memory, and prioritized aging split jobs.
- Recovered stale worker heartbeats, guarded task completion against cancellation and reassignment races, and recorded CPU fallback reasons and per-device outcomes.
- Evicted ASR, GGUF, decision, and embedding caches safely during model deletion; kept selected GPUs checked in CPU mode and restored history filters from the URL.
- Forced the GPU image to compile and verify the llama.cpp CUDA backend during build.

## 2026-10-09 — AMINAZADI

- Isolated PyTorch wheel downloads from dependency resolution so all transitive Python packages are installed through the configured Iranian PyPI mirror instead of `files.pythonhosted.org`.
- Switched deployment Python package installation to the free Novin Cloud PyPI mirror hosted in Iran while preserving explicit overrides and the dedicated PyTorch wheel index.

## 2026-10-03 — AMINAZADI

- Added regression coverage for versioned GPT-4o transcription aliases so 9Router never sends unsupported verbose JSON to those models.
- Requested provider-compatible JSON for every GPT-4o transcription variant, including mini models, while retaining timestamped verbose JSON for compatible 9Router ASR models, then normalized both response shapes internally.
- Replaced execute-all multi-model processing with ordered first-success failover, including per-model retries, explicit skipped runs, crash recovery, and aggregated all-model failure details.
- Made every enabled cached 9Router model executable through the same catalog and dispatch contract while preserving installed local-model priority.

## 2026-10-02 — AMINAZADI

- Documented and verified the existing 9Router transcription prompt passthrough used by Sedasanj's new admin-managed ASR prompt.
- Marked synchronized 9Router catalog models as remotely ready regardless of their upstream owner, preventing clients from treating them as uninstalled local models.
- Added authenticated native `/v1/embeddings` inference for installed transformer embedding models, including safe pinned model registration, installation validation, model-catalog exposure, and OpenAI-compatible responses.
- Added decision and embedding capabilities to the 9Router proxy/catalog synchronization so callers can explicitly choose native AISERVICE or 9Router routing.

## 2026-10-01 — AMINAZADI

- Pinned AISERVICE data and object-storage volumes to stable, configurable Docker volume names so moving the repository does not create an empty replacement data store or invalidate persisted API-key access.

## 2026-09-30 — AMINAZADI

- Enabled the `/v1/ninerouter/chat/completions` proxy capability used by the customer assistant, preventing valid chat requests from being rejected as an unsupported 9Router path.
- Allowed installed local ASR and LLM models to remain independently selectable while 9Router providers are enabled, preventing native AISERVICE requests from being rejected by an unrelated remote-model configuration.

## 2026-09-29 — AMINAZADI

- Renamed decision engines to GLiNER2.5 Multi Decide and Laya Multilingual and added typed criteria validation plus a versioned normalized decision result.
- Updated decision bundle validation and the Admin model selector for the new local decision runtimes.

## 2026-09-29

### AMINAZADI

- Fixed Docker runtime propagation of `ASR_9ROUTER_SECRETS_KEY` for encrypted 9Router credentials.

## 2026-09-29 — AMINAZADI

- Fixed 9Router settings panel injection on direct admin settings pages.
- Added opt-in gzip audio ingestion for multipart and direct ASR uploads with bounded decompression and decoded-size validation.

## 2026-09-29 — AMINAZADI

- Added persistent 9Router model synchronization and authenticated capability proxy routes.
- Added independently switchable 9Router ASR and Text/Chat providers with encrypted persisted credentials, model discovery, admin controls, and durable queue execution.
- Added CPU-only typed Decision Models support with secure artifact registration, durable tasks, scoped API access, offline runtime loading, and model lifecycle validation.
- Added GLiNER2 and Laya decision runtime engines, confidence abstention, decision queue capacity controls, and administration form support.
- Fixed Hugging Face Xet/LFS manifest resolution and engine-specific artifact validation for GLiNER2 and Laya.
- Fixed offline local Laya loading by removing an unsupported runtime argument.
- Upgraded GLiNER2 to the official local-inference runtime that exports AutoExtractor.
- Added decision task status and result response support.
- Restored the default confidence threshold when a decision request omits it.
- Normalized native GLiNER2 and Laya decision result envelopes with confidence metadata.
