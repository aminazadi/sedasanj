# Changelog

## 2026-10-22 — AMINAZADI

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
