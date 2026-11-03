# Changelog

## 2026-11-04 — AMINAZADI

- Added a two-second tone after the Jalase-Negar countdown and before microphone capture, and made the countdown digits bolder.
- Matched the Jalase-Negar recording header buttons and added a three-second audible countdown between the wind effect and microphone capture.
- Compacted the Jalase-Negar meeting player controls and moved the playback timer beside them below the waveform, removing the duplicate title above it.
- Removed post-recording retranscription from Jalase-Negar. Meeting details now show the saved transcript and audio player, and the meeting list no longer retries processing failures by transcribing the saved audio.
- Added live transcription to Jalase-Negar recording: a long-lived isolate runs Silero VAD on the microphone stream and decodes each finished utterance with the selected Shenava model, shows it in a live panel while recording, and saves it as a draft (ASR identity `…|segmenter:silero-vad-live`) that the full transcription replaces; live failures or a slow phone never affect the recording, and the feature can be switched off from the recording screen.
- Changed Jalase-Negar recording to disperse the illustration into windblown particles and show the PCM waveform and compact timer below the live transcript.
- Redesigned the Jalase-Negar meetings list: date-grouped sections with pinned headers, search and status filter chips, square cards with soft shadow, transcript preview, per-stage progress panel, retry on failed meetings, swipe-to-delete with undo, rename and share actions, skeleton loading, and a recovery action on load errors.
- Changed the Jalase-Negar settings QR scan into a full-screen camera with a centred square scan frame (corner brackets, sweeping line, torch and close buttons); only the framed area is decoded.

## 2026-11-03 — AMINAZADI

- Made Shenava Koochik v1.5 RNNT (INT8) the recommended Jalase-Negar model, ported the platform's turn consolidation (`consolidate_segments`) and energy VAD to Dart against shared contract vectors, and recorded the segment contract fields (confidence, speaker, timestamp source, source) plus an ASR identity per meeting (database v6).
- Added a server-parity transcription mode to Jalase-Negar (server energy VAD, regions decoded as is, clips up to 30 minutes) for region-by-region comparison with the platform transcript; normal transcription still uses Silero VAD.
- Added the ASR parity contract (`sedasanj/docs/asr-parity-contract.md`) with shared fixtures for preprocessing constants, gain, transcript normalization, segment merging and the segment schema, plus server and Jalase-Negar tests that lock them; recorded the current app/server normalization gaps, including `ۀ` collapsing to a plain `ه`.
- Added `sedasanj/scripts/asr_eval.py` (stdlib WER/CER scoring and baseline comparison) and the ASR golden-set layout under `sedasanj/test_data/asr_golden/`, with audio, references and system outputs git-ignored.

- Added a fixed bottom waveform audio player (play/pause, seek, mute, speed, share) to the Jalase-Negar meeting detail screen, matching the web panel player.

- Added the shared processing indicator and installed app version to the Jalase-Negar splash screen.

- Added animated diamond pulse waves to the meeting recording start button.

- Placed the recording timer immediately below the meeting illustration.

- Added a compact, dotted meeting recording illustration inspired by the web panel artwork.

- Matched the Jalase-Negar recording screen start button size and green border to the bottom navigation button.

- Changed Jalase-Negar navigation to include a dedicated recording button and refreshed meeting and settings tabs.
- Removed the obsolete MikroTik Fadaeian Arvan setup document.
- Added Shenava Koochik v1.5 RNNT CUDA inference using FP32 encoder/decoder/joiner artifacts, preserved INT8 CPU inference, and added a model-card action to complete GPU files for existing installations with actionable missing-artifact diagnostics.
- Fixed the AI dashboard resource grid to show six cards in two rows of three on desktop, with two columns on tablets and one on phones.

## 2026-11-02 — AMINAZADI

- Added CUDA scheduling for Shenava NeMo CTC models with the pinned Sherpa CUDA 12/cuDNN 9 wheel, per-GPU isolated inference, bounded execution, CPU fallback under the existing scheduler policy, and coded worker failures.
- Replaced resource bars with live speedometer gauges, separated GPU compute from VRAM occupancy, added temperature/power/fan readings, and sampled resources independently every second with stale-data feedback and explicit network rate scales.
- Fixed AI GPU image library discovery by registering wheel-provided NVIDIA and PyTorch library paths with the system loader; added a fresh-process cuBLAS/cuDNN symbol check, regression tests, and Persian troubleshooting for SS-DEP-0001 to prevent broken GPU images from reaching inference.

## 2026-11-01 — AMINAZADI

- Redesigned the Jalase-Negar Flutter app (`jalase-negar/`) to match the SedaSanj panel: brand palette (`#F2F0EF`, `#B2AC88`, `#898989`, `#4B6E48`), zero border radius, no shadows, dotted patterns, green dotted app bar, dotted section title bands and square badges, via a new shared theme (`lib/app/theme.dart`) and widgets (`lib/app/widgets/ss_widgets.dart`). Reused the SedaSanj office line art, empty-state illustration and pattern images (`assets/images/brand/`) and the Vazirmatn variable font as static 350/500/600 instances. Verified on the Android emulator only; iOS and the lab matrix were not run.
- Removed all on-device analysis from Jalase-Negar: local LLM minutes (fllama/Dorna), transcript correction, online AI transcription, license gating and their settings; the embedded online-AI API key is gone from the source and must still be revoked by its owner. Local database migrates to version 4 (drops minutes, corrections and online transcripts) and meeting statuses now cover the upload/processing flow. Dropped unused dependencies, fonts and Android build hacks.
- Added the Jalase-Negar SedaSanj connection flow: pairing payload parser (`sedasanj.jalase-negar.config` v1, expiry and https checks), typed `ApiClient` with Persian actionable errors (401 reconnect, 402 top-up, pairing/limit codes), token kept in secure storage, and a connection screen with QR scan, config file and pasted-config import plus disconnect. Added camera permission for QR scanning.
- Reworked Jalase-Negar recording (J3): mono 16 kHz capture with a microphone foreground service, sample-based timing, 45–90 s WAV chunks cut at silence and registered in a new `upload_chunks` table (DB v5), meeting row written at start so killed recordings are repaired and recovered on next launch, disk-space guard (500 MB), and surfacing of OS interruptions. Added chunk writer and WAV repair tests.
- Added the Jalase-Negar upload queue (J5): chunks are uploaded while the meeting is still recording (two at a time, sha256-verified, exponential backoff with jitter), the session is created idempotently and resumed from the server's received chunks, finished once every chunk is in, then server processing is followed to completion. 401/402 stop the queue with Persian guidance, a server-deleted meeting is marked failed, and local chunk files are removed after the server accepts the finish. The list shows upload progress. Added `test/tools/fake_sedasanj.py` for emulator testing and queue unit tests with a fake API.


## 2026-10-31 — AMINAZADI

- Replaced the Font Awesome spinners in the FreePBX module page (version history, update download button, update progress header and the running step) with the assistant's four-square loader (`.sj-loader`), and removed the unused `.icon-spin` style from the ASR dashboard. `php -l` was not run (PHP is not installed locally).

- Released FreePBX module 1.5.5 with the existing internal-call direction mapping and synchronized release metadata; ZIP integrity passed, but PHP 7.4/8.2 tests could not run because the Docker daemon was unavailable, and PBX lab validation remains pending.

- Marked FreePBX `exten-*` recordings as `internal` in the recording hook (`mix-stereo.php`) and the ingest mapper so extension-to-extension calls reach the platform with `direction=internal`; the platform still classifies calls from the synced extension list. The `exten-` filename prefix and `php -l` under 7.4/8.x are not yet lab-confirmed (⚠ needs lab confirmation); test added to `IngestDestinationTest.php`.
- Added explicit Issabel-only installation guards, separated the module UI script, and recorded final beta validation with pending PBX lab certification.
- Added the Issabel 4/5 beta module, shared PBX engine, legacy PHP gateway, original-recording preservation, generated-dialplan adapters, verified installation backups and rollback.
- Replaced the column checkboxes in the calls export dialog with the shared `ToggleSwitch` component used elsewhere in the panel.
- Redesigned the organization dashboard around chart-only KPIs (conversion, quality and SLA gauges, daily trend, call-to-opportunity funnel, operator comparison, tasks, unanswered call types) and moved numeric cards, tables and secondary analyses into a collapsible details section stored in the `details` URL parameter; the customer-satisfaction block is unchanged.
- Fixed module log viewer overflow and added an ALL minimum-level filter.
- Fixed module 1.5.3 inbound recording direction, escaped MixMonitor filename filters, and answered-extension recovery for rejected uploads.

- Fixed missed-call labels to show a single concise status and aligned caller and destination details in the calls table.
- Documented FreePBX module licensing, third-party attribution, release-signing status, and GPL-compatible protection measures.
- Fixed FreePBX module recording hooks failing to locate answered-call audio legs when Asterisk normalizes hyphens in the post-record filename; added regression coverage.

## 2026-10-30 — AMINAZADI

- Fixed module 1.5.1 metadata causing FreePBX bootstrap to pass an array to stristr() after upload; retained coded PHP-extension checks and documented backup-first panel recovery.

- Replaced the outdated module 1.3.7 ZIP with a verified module 1.5.0 installation archive after passing PHP 7.4 and 8.2 lint and module tests; generated release archives remain outside version control.
- Added PBX extension sync from the FreePBX module: calls between two synced extensions are now recorded as internal, extension numbers show a contact, operator or PBX name, and each extension can be linked to a phonebook contact and an operator from the phonebook page (migration `0060_pbx_extensions`).

## 2026-10-29 — AMINAZADI

- Fixed the existing-organization form flashing briefly while automatic phone login completes.
- Added automatic login submission when a six-digit SMS or authenticator OTP is completed across client, organization and admin sign-in flows.
- Replaced oversized admin and client panel PNG artwork with display-sized high-quality WebP assets and deferred below-the-fold image decoding and loading.

## 2026-10-29 — AMINAZADIAN

- Hardened automatic FreePBX module updates with a signed, expiring release manifest, refusal of older releases, and support for up to three trusted keys during key rotation.
- Added module diagnostics reports (hourly doctor results) with an admin health view, the `requeue-failed` tool for recordings in `failed/`, and a CI workflow for the module (PHP 7.4 to 8.3), API and web apps.
- Fixed ASR failure classification (silence, httpx timeouts, tenant credit errors), finished dead-lettered webhooks as complete calls, stopped echoing submitted values and internal errors in API responses, and made non-5xx HTTP errors non-retryable.
- Added Alertmanager with alert rules for workers, provisioning, 5xx rates, ingest rejections and webhooks; applied no-new-privileges and dropped capabilities for the Python services.
- Agent: key/account rejections now pause calls instead of dead-lettering them, the call start time comes from the Uniqueid, delivered MixMonitor legs are removed, and ffmpeg has a timeout.
- Repaired stale tests so the full Python suite passes.

## 2026-10-29 — AMINAZADIAN

- Added the help center: staff manage articles, categories, error-code mappings and image/video media in the admin panel; readers open `/help`, and the FreePBX module links every error code to `/help/errors/<CODE>`. Article HTML is rebuilt from an allowlist, uploads are validated by content, and a seed script creates draft articles for the most common module errors.

## 2026-10-29 — AMINAZADI

- Hardened FreePBX module 1.3.9: filtered all caller-controlled MixMonitor command arguments against shell injection, added CSRF tokens and POST-only enforcement to settings save, configuration import and update start, and validated the manual settings form server-side.

## 2026-10-29 — AMINAZADI

- Rebuilt backup and restore: tenant databases, a host-side audio mirror and an encrypted secrets bundle (`.env` keys, database roles, release signing seed) are now backed up with `pg_restore --list` verification, SHA-256 checksums, atomic temp-then-rename writes, keep-last-N pruning and an optional off-host rsync target; restore now stops every writer, takes a pre-restore snapshot, restores into fresh databases swapped in by rename with `--exit-on-error --single-transaction`, re-applies role grants, requires confirmation (`--yes` to skip), and a new `restore_tenant.sh` restores a single tenant. Documented a monthly restore drill.
- Fixed recording uploads whose FreePBX destination is a nonnumeric dialplan label by using the attributed agent extension as the dialed number.
- Fixed missed-call API idempotency conflict handling to use the actual unique key columns in module ingestion.
- Fixed FreePBX global database handle corruption during CDR lookups in module 1.3.7.
- Fixed background FreePBX CDR bootstrap variable scope in module 1.3.6.
- Fixed FreePBX voicemail configuration parse-back and persisted active module tabs in the URL across all form actions in module 1.3.5.

## 2026-10-28 — AMINAZADI

- Changed FreePBX update-check and release-history error messages to English and released module 1.3.4.
- Changed the FreePBX release-history tab title to English and released module 1.3.3.
- Added a direct FreePBX custom-CDR fallback and released module 1.3.2 after field validation exposed an environment-specific include parsing failure.
- Fixed FreePBX missed-call validation to resolve effective CDR options from included configuration files and prepared module release 1.3.1.
- Corrected module-release back-link arrow direction across the administration pages.
- Fixed FreePBX module uploads by provisioning and backing up a persistent release-signing key and embedding its public key into every published module archive.
- Added recoverable Redis startup repair for corrupted AOF persistence and documented the required host memory-overcommit configuration.
- Fixed API and worker image builds by retrying Python package mirrors independently when an index returns a truncated or malformed response.
- Persisted Sedasanj and AISERVICE model downloads in Git-ignored, build-excluded project-root directories and reused them across deployments.
- Added automatic one-time migration from the previous Docker model volumes.

## 2026-10-28 — AMINAZADI

- Configured the official PyPI index as an additional package source during API and worker image builds.
- Replaced the official PyPI extra index with Aliyun and Tsinghua mirrors for API and worker image builds.
- Added a PyPI fallback when the configured package mirror fails during API image dependency installation.

## 2026-10-28 — AMINAZADI

- Fixed FreePBX configuration imports by supporting the optional missed_calls section and reporting precise section validation errors.
- Completed the FreePBX missed-call upload path with CDR polling, JSON delivery, retry handling, admin controls, and CDR readiness feedback.
- Kept missed-call uploads disabled by default in generated configuration and added a shared web/PHP contract fixture.
- Added the editable FreePBX module source and prepared release package version 1.2.1.

- AMINAZADI: Updated the homepage hero headline to «بدون صداسنج هیچ مرکز تماسی موثر نیست».
- AMINAZADI: Replaced the landing page's customer voice call to action with the quick demo section shown in the reference.

## 2026-10-16 — AMINAZADI

- Corrected the bronze and gold plan artwork assignment on the homepage.
- Reassigned the supplied bronze and gold illustrations to match their colors and plan names.
- Changed the homepage pricing heading to «پلن‌های مقرون بصرفه».
- Expanded the homepage privacy and deployment descriptions with organization-specific database and self-hosting details.
- Expanded the homepage access-control description with role-based permissions for relevant sections and data.
- Redesigned the homepage footer with a contact callout, phone link, trust badge placeholders, and grouped quick links.
- Displayed the footer phone number in Persian digits outside a button.
- Increased the footer phone number size.
- Added a subtle dotted pattern to the footer background.
- Added an «درباره صداسنج» heading to the footer brand section.
- Added admin settings for the footer phone number and trust badge HTML, displayed in an isolated frame.

## 2026-10-16 — AMINAZADI

- Tightened plan card spacing and enabled horizontal mobile scrolling with the next card partially visible.

## 2026-10-16 — AMINAZADI

- Replaced the homepage plan card symbols with the supplied demo, bronze, silver, and gold illustrations.

## 2026-10-16 — AMINAZADI

- Removed the «خوش آمدید» heading from the login page.

## 2026-10-16 — AMINAZADI

- Removed the login helper text «برای ورود به پنل، اطلاعات خود را وارد کنید.».

## 2026-10-16 — AMINAZADI

- Removed the «با شماره موبایل شروع کنید» prompt from phone login.

## 2026-10-16 — AMINAZADI

- Reduced the vertical spacing and padding of the login method tabs.
