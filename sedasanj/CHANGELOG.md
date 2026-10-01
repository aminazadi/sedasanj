# Changelog

## 2026-10-01 — AMINAZADI

- Removed gray from both sidebars and established explicit states: green base, warm-white active navigation, beige hover/account surfaces, and green active indicators.
- Applied the exact four supplied palette values directly in both panel stylesheets: green navigation/actions, warm-white canvas/cards/inputs, beige borders, and gray secondary content; removed all corner radii from authenticated customer and admin surfaces, including charts and tooltips.
- Unified the customer and admin panel color systems around the shared `#4B6E48`, `#B2AC88`, `#898989`, and `#F2F0EF` palette, including navigation, controls, states, and data visualizations.
- Applied the grouped desktop sidebar, responsive right-side drawer, standalone white logo, and role-aware navigation to the customer panel.
- Fixed the sidebar logo filter so the source image background blends into the dark sidebar instead of rendering as a white rectangle.
- Simplified the admin sidebar header to the standalone white Sedasanj logo on its dark background.
- Redesigned the admin navigation as a grouped desktop sidebar and an accessible right-side drawer with a hamburger trigger on tablet and mobile layouts.
- Pinned all production database, cache, object-storage, model-cache, and observability volumes to stable, configurable Docker volume names so repository directory changes cannot create empty replacement data stores.

## 2026-09-30 — AMINAZADI

- Ensured idempotent seed runs provision the legacy active subscription required by assistant entitlements, including repair of tenants created after commerce migrations.
- Added configurable external DNS resolvers to AI-facing application containers and classified provider DNS/network failures as retryable instead of terminal generic ASR failures.
- Fixed native AISERVICE ASR requests being rejected when the upstream service also has an independently configured 9Router speech model.
- Added a complete local environment template and corrected development commands to run Alembic, seeding, and Uvicorn through the project-managed Python environment with the local Docker ports.
- Switched the local PostgreSQL image to PostgreSQL 17 with pgvector so the full local migration chain can run without rebuilding or deleting existing local data.
- Restricted every AI workload to the single admin-managed AISERVICE connection, added explicit per-model endpoint routing for ASR, durable analysis, assistant chat, typed decisions, and embeddings, and made AISERVICE ASR uploads always use documented gzip multipart transport.
- Unified every admin and customer date input on the shared Jalali date-time picker, including KPI goal windows and customer/admin installation scheduling.
- Added an admin-managed LLM provider switch shared by call analysis and the intelligent assistant, ensuring AISERVICE routing no longer depends on the deployment environment default.
- Normalized object-shaped top-level LLM sentiment output before extraction validation so valid analyses no longer fail after JSON repair.
- Repaired legacy tenant balance-cache nulls, added runtime normalization for billing and payment mutations, and enforced zero defaults to prevent admin top-up failures.
- Fixed tenant control-plane migration compatibility with asyncpg by executing each PostgreSQL command separately.
- Fixed asyncpg compatibility across identity projection, tenant backup, hybrid knowledge, and sales KPI migrations by preventing multi-command prepared statements and added migration regression coverage.

## 2026-09-29 — AMINAZADI

- Hardened the sales KPI center after review: enforced operator-scoped CRM metrics and private filter data, corrected AI opportunity denominators and cumulative funnel math, added prior-period deltas and anomaly actions, applied the configured SLA and confidence thresholds, activated versioned sales taxonomies in prompts and stored results, made CRM ingestion concurrency-safe, and sequenced completion webhooks after operator scoring.
- Added regression coverage for KPI ratios, cumulative funnel behavior, opportunity eligibility, and taxonomy validation.

## 2026-09-29 — AMINAZADI

- Added a tenant-safe sales KPI center with AI/CRM outcome separation, conversion coverage, sales funnel, campaign/source analysis, operator coaching, action center, team and time-bound membership management, versioned KPI settings, dated goals, and responsive manager/operator dashboards.
- Added structured sales extraction with evidence, confidence, funnel stage, objections, product, win/loss reason, and next action; added CRM-authoritative idempotent outcome ingestion and signed `sales.insight` webhook delivery.
- Extended VoIP ingest with campaign, source, and external reference metadata while preserving unknown attribution when metadata is absent.
- Added automated database-per-organization provisioning, encrypted tenant connection registry, lazy tenant routing, isolated PostgreSQL roles, pgvector/Apache AGE database bootstrap, resumable legacy-tenant migration, validation, rollback windows, provisioning worker, and admin migration monitoring.
- Added canonical call-to-operator assignments, strict self-only operator retrieval, operator access to the call assistant, immutable privacy instructions, and deterministic polite refusal for cross-tenant and cross-operator requests.
- Added the pinned PostgreSQL 16 image build with pgvector and Apache AGE plus tenant migration configuration and security tests.
- Added a central identity source of truth with durable, idempotent operator projection, bounded provisioning retries, sequential fleet schema upgrades, encrypted per-tenant dumps, retention cleanup, checksums, and backup visibility in the admin panel.
- Added AISERVICE typed-decision settings, scoped credentials, GLiNER2.5 primary scoring, Laya fallback, confidence-aware operator score review states, and bounded 30-second remote-ASR chunks for long calls.
- Added opportunistic gzip multipart encoding for AISERVICE ASR uploads using its documented `audio_encoding` contract.
- Added five-level decision rubrics and removed LLM-generated JSON from operator scoring.
- Added tenant-aware durable outbox dispatch, worker database resolution, payment callback routing, maintenance fan-out, canonical operator-call authorization, and stale identity-projection rejection.
- Added resumable destructive-safe tenant copying with maintenance-first draining, zero-row validation, canonical content digests, guarded rollback, and automatic vector/AGE knowledge backfill.
- Added admin-managed embedding provider settings and hybrid assistant retrieval with model-scoped vectors and tenant-local Apache AGE graph context.
- Hardened tenant cutover and fleet upgrades against stale-source fallback, preserved pre-migration tenant states, added runtime identity/schema/extension/graph verification, and removed pooled session-level RLS privilege leakage.
- Routed platform operations and commerce administration across tenant databases, added tenant-safe financial mutations and global plan-reference synchronization, and fixed job draining under forced RLS.
- Paused outbox delivery for non-active tenants, prevented stale-source outbox resolution after cutover, and re-armed copied queued jobs to avoid loss during the maintenance boundary.

## 2026-09-27 — AMINAZADI

- Added an admin-selectable, independently credentialed OpenAI-compatible ASR provider for 9Router.
- Changed the AI provider default and saved legacy VoiceSanj URL normalization to HTTPS, with a clear redirect error.
- Released FreePBX module 1.1.7 with read-only answered-extension lookup from exact-uniqueid CDR records and sidecar-safe JSON queue handling.
- Released FreePBX module 1.1.6 with sidecar-aware sweep filtering and explicit empty-recording diagnosis.
- Released FreePBX module 1.1.5 with lossless INI configuration encoding and deployed-runtime verification.
- Released FreePBX module 1.1.4 with legacy SQLite compatibility and recovery of inbound metadata after pre-upload state failures.
- Released FreePBX module 1.1.3 with GSM executable permission repair and runtime-aware import validation.
- Released FreePBX module 1.1.2 with verified migration from legacy core-patch backups and fail-closed handling for mismatched states.
- Released FreePBX module 1.1.1 with mandatory pre-installation backups, checksum verification, and a controlled restore helper.
- Added authenticated ingest configuration validation for API keys, transport, and optional ZIP passwords.
- Marked insufficient-credit and quota responses as retryable without losing queued calls.
- Added separate browser-generated FreePBX JSON and Python Agent TOML downloads.
- Added local re-entry and validation for exporting existing API-key configuration without storing the secret.
- Added Python Agent credit-blocked scheduling and durable dead-letter metadata.
- Added the standalone FreePBX module 1.1.0 release with PHP 7.4 compatibility, versioned import, atomic apply and rollback, explicit transports, durable queue states, retention cleanup, and pinned binary checks.
