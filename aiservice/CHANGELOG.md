# Changelog

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
