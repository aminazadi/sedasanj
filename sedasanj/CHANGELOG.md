# Changelog

## 2026-10-01 — AMINAZADI

- Removed the divider from the call-detail hero and tightened its vertical padding, header spacing, content gap, title spacing, and metadata wrapping.
- Added the call-analysis fine-dot texture to the full navigation sidebar in both the customer and admin panels.
- Removed the circular clipping from the assistant new-conversation action so it follows the panel's square, radius-free design language.
- Localized customer webhook event switch labels into Persian while preserving their existing API event identifiers.
- Stabilized animated toggle alignment with explicit track and thumb geometry so utility generation and RTL inheritance cannot shift the control during transitions.
- Added direction-aware animated thumb movement and track-color transitions to every shared admin and customer toggle.
- Reworked toggle thumb placement with direction-aware flex alignment so RTL states use the correct logical side and the thumb remains evenly inset inside the track.
- Vertically centered the shared toggle thumb and enforced the primary green track color independently of RTL direction and generated utility availability.
- Fixed shared toggle thumb positioning in RTL layouts by isolating its movement from inherited text direction and containing it within the track.
- Replaced every checkbox in the admin and customer panels with one shared accessible toggle-switch component, including settings, plans, checkout consent, webhook events, protected exports, and follow-up completion.
- Stretched the assistant send button to the full composer height, including the keyboard-shortcut hint row.
- Corrected the follow-up tasks palette with a high-contrast green active filter, beige inactive filters, distinct open and completed status treatments, and palette-aligned task cards.
- Added a fast queued typewriter effect for streamed assistant responses and prevented the completed message from skipping unfinished animation frames.
- Added `Ctrl + Enter` message submission to the assistant composer with an inline shortcut hint while preserving plain Enter for new lines.
- Added distinct square user and assistant avatars beside every chat message with clear spacing from the directional bubble tails.
- Added compact bottom-aligned directional tails to user and assistant message bubbles with seamless rotated fills that preserve each bubble border without hollow or detached outlines.
- Replaced the assistant's three-dot typing indicator with an animated shimmer treatment for the Persian thinking-and-result status text.
- Added an accessible animated three-dot typing indicator while the assistant is waiting to stream its first response content.
- Unified the desktop assistant conversation list and chat area into one bordered panel separated by a single divider.
- Replaced blue assistant chat accents with the shared green, beige, and warm-white palette, fixed the prompt composer at the bottom of the visible chat panel, and removed its floating shadowed container so the full footer is the prompt area.
- Added a palette-matched chat icon to the assistant empty state when no messages exist.
- Made customer and admin dialogs vertically scrollable on mobile viewports so all fields and actions remain reachable.
- Converted table filter panels in the customer, organization, operator, and admin interfaces into collapsed mobile accordions while preserving their expanded desktop layout.
- Contained every customer and admin table's horizontal overflow within its own card or scroll wrapper on mobile, preventing tables and grid children from widening the page.
- Removed the outer border from the assistant conversation drawer on mobile while retaining the desktop panel border.
- Added route-aware page titles beside the mobile hamburger menu across dashboard, call, assistant, reporting, account, setup, payment, and informational pages.
- Removed the Sedasanj logo beside the customer panel title in the mobile header while preserving the logo inside the navigation drawer.
- Added a responsive assistant conversation drawer on mobile with a compact trigger, backdrop, Escape handling, and automatic close after selection.
- Switched the assistant conversation sidebar to a light surface while preserving the main sidebar's navigation structure, spacing, active states, and interactions.
- Replaced the assistant sidebar's gray surface with a dark forest treatment and converted the new-conversation action into an accessible floating button.
- Fixed the assistant conversation sidebar to the desktop viewport with full-page height and independent internal scrolling.
- Matched the assistant conversation panel exactly to the main sidebar structure and navigation states while retaining a distinct neutral background.
- Removed the filled background from both sidebar account cards and adjusted the logout control for the green sidebar surface.
- Restyled the assistant conversation list to match the main panel sidebar, including grouped navigation, full-width chat items, active-state treatment, action controls, and bounded scrolling.
- Changed role and identifier text in both sidebar account cards to warm white for consistent contrast.
- Replaced blue across the in-progress call pipeline and primary chart palette with vivid system-aligned greens.
- Unified customer and admin sidebar hover styling with the active-item green and warm-white color treatment, removing the third gray navigation state.
- Replaced muted chart colors with a vivid accessible categorical palette across sentiment, trajectory, speaker, trend, and sales-funnel visualizations.
- Added a distinct neutral-gray hover state with warm-white text and icons to every customer and admin sidebar item, including the active route.
- Further softened the processing-card dot texture for a more understated appearance.
- Reduced the processing-card dot opacity for a softer background texture.
- Increased the processing-card dot contrast and applied the pattern through an override-safe background declaration.
- Added a subtle fine-dot background pattern to the call analysis pipeline card.
- Persisted the selected call-audio playback speed in browser storage and automatically restored it for subsequent recordings.
- Refined the call waveform with left-to-right seeking, a clearer progress indicator, uniform controls, playback-speed cycling, and authenticated audio download.
- Replaced the compact native call audio control with a responsive waveform player featuring playback, seeking, elapsed time, duration, and mute controls in the call header.
- Increased processing-timeline status icon size and adjusted adjacent spacing for clearer scanning.
- Replaced the processing-report text arrow with a larger outlined SVG chevron and retained the open-state rotation.
- Replaced the call-detail telephone emoji and heavy filled tile with a crisp outlined phone icon on a light, palette-matched surface.
- Changed all call-detail header typography, numbers, controls, and icons to black for maximum clarity.
- Removed green typography and icons from the call-detail header, retaining green only as the top accent rule.
- Replaced green in the call-header badges with light warm-white and beige surfaces plus neutral gray text.
- Reworked the call-detail header with the exact shared palette, replacing the blue gradient, blue icon treatment, red status, and mismatched action-menu colors.
- Standardized RTL select controls in both panels with a palette-matched chevron and consistent spacing from the left edge.
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
