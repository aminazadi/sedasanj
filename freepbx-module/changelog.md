# Changelog

## 1.4.0 — AMINAZADI

- Installation from FreePBX Module Admin now succeeds without root: it registers the module and shows an "Activation required" notice with the single root command (`activate.sh`) that creates the service, update helper and recording hook. `install.sh` and `fwconsole ma install` as root still provision everything in one step.
- Declared `<depends>` (PHP 7.4+, curl/zlib/json/simplexml, core, callrecording, cdr) and `<supported>` FreePBX 15, 16 and 17 in `module.xml`, and replaced the file-name `<changelog>` with inline text. FreePBX version detection now reads the first version number only (15.0.17 is no longer mistaken for 17).
- Added stable error codes (`SS-<AREA>-<NNNN>`, `ErrorCatalog`) and a structured, redacting logger: secrets, bearer tokens and configured passwords are removed, control characters cannot forge log lines, phone-like fields are masked, rotation is locked and new log files are mode 0640.
- Upload failures are classified once: HTTP 401/403/404/405 and archive/key errors now pause the recording and its queue (shown as "Paused: key or account") instead of moving every queued recording to `failed/`; credit pauses are unchanged; per-recording data errors still fail permanently; proxy and unknown errors are retried. A tick stops early when the endpoint is down, uploads time out relative to file size, and the server request ID is logged.
- A failed local archive copy (GSM encoder, ffmpeg, wideband audio) no longer blocks delivery. A failed stereo merge now logs `SS-HOOK-1003` and delivers the mono mix instead of leaving the call stranded. The merged file is created as `.part` and renamed only after its metadata sidecar exists.
- Voicemail messages that fail are retried at most every six hours instead of every sweep. Queue jobs and the recording hook now share one state record per call.
- `callrecording` patching now supports FreePBX 15, tolerates a core file that already contains the patch (upstream adoption) and is verified against the real 15, 16 and 17 sources.
- Installation backups no longer archive the recording spool. Helper classes (`UploadError`, `StagingError`, `WavFile`, ...) are autoloadable.
- Fixed the Failed counter counting metadata sidecars; added end-to-end tests that run the hook and uploader against a stub server on PHP 7.4 to 8.3 (`scripts/test-freepbx-module.sh`).

- Automatic updates now require a signed, expiring release manifest bound to the exact download (version, digest, size); older or replayed releases are refused and up to three public keys are trusted at once for key rotation.
- Added `requeue-failed.php` (put recordings from `failed/` back into the queue), hourly diagnostics reports to the Seda Sanj API, a single-instance lock for the service, and `Retry-After` handling for HTTP 429.

## 1.3.9 — AMINAZADI

- Security: every caller-controlled value in the MixMonitor post-recording command (`CALLFILENAME`, `UNIQUEID`, `CALLERID(num)`, `CDR(dnid)`, `CDR(duration)`, `CDR(dst)`, `FROM_DID`) is now passed through Asterisk `FILTER()` and revalidated by `mix-stereo.php`, closing a shell-injection path from crafted SIP user parts. The globals block is installed from the single shipped `dialplan/globals-custom-mixmon.conf` and replaced on upgrade when it differs.
- Security: saving settings, importing a configuration and starting an update now require a POST request with a per-session security token (CSRF protection); the former GET-driven save is rejected.
- Added server-side validation of the manual settings form (https endpoint, numeric ranges, enumerations, regular expressions, absolute paths, no line breaks) before anything is stored or written to config.ini.

## 1.3.8 — AMINAZADI

- Fell back to the attributed agent extension when FreePBX supplies a nonnumeric dialplan label as the call destination, preventing valid recordings from being rejected by ingest validation.

## 1.3.7 — AMINAZADI

- Fixed CDR lookups overwriting the FreePBX global database handle and breaking administration page rendering.

## 1.3.6 — AMINAZADI

- Preserved FreePBX bootstrap globals when connecting to CDR from the background poller and answered-extension lookup.

## 1.3.5 — AMINAZADI

- Fixed parse-back validation for Base64-encoded voicemail spool and folder settings.
- Persisted the active administration tab in the URL across validation, save, reload, and update actions.

## 1.3.4 — AMINAZADI

- Changed the update-check and release-history error messages to English.

## 1.3.3 — AMINAZADI

- Changed the release-history tab title to English.

## 1.3.2 — AMINAZADI

- Added a direct FreePBX custom-CDR fallback so readiness validation honors `cdr_general_custom.conf` even when include parsing is unavailable.

## 1.3.1 — AMINAZADI

- Fixed missed-call readiness validation to resolve Asterisk CDR include files, including FreePBX-managed `cdr_general_custom.conf` overrides.

## 1.3.0 — AMINAZADI

- Added in-page update checks: every visit to Admin > Seda Sanj asks the Seda Sanj API for newer releases and shows a banner with the release notes.
- Added one-click automatic updates: the release is downloaded, checked against its SHA-256 and Ed25519 signature, backed up, installed and health-checked by a root-owned helper, with automatic rollback on failure and live step-by-step progress.
- Added a "تغییرات نسخه‌ها" (release history) tab.
- The installer now provisions `/usr/local/sbin/sedasanj-recuploader-update`, the release signing key and the matching sudoers entry. Automatic updates require the PHP sodium extension.
- This release must be installed manually once (install.sh or `fwconsole ma install`); later releases can be applied from the page.

## 1.2.1 — AMINAZADI

- Completed the opt-in missed-call CDR poller, JSON ingest, retry spool, service scheduling, settings, and readiness checks.
- Added forward-compatible parsing for the optional missed_calls profile section and specific unknown/missing section diagnostics.
- Standardized CDR epoch handling through the MySQL session timezone and fixed pagination placeholders for native PDO prepares.
- Added a shared web/PHP configuration contract fixture.


## 1.2.0 — AMINAZADI

- Added an opt-in voicemail sweeper with stable message deduplication, source-preserving staging, transcoding, retry, and folder/mailbox filters.
- Added FreePBX settings, status counters, CLI scanning, and backward-compatible configuration profile support for voicemail uploads.
- Routed voicemail audio to the Seda Sanj voicemail ingest endpoint without changing mailbox contents.

## 1.1.7 — AMINAZADI

- Added read-only CDR lookup for unambiguous inbound answered-extension attribution.
- Kept the extension unset when CDR evidence is missing or ambiguous.
- Prevented metadata sidecars from being consumed or migrated as JSON queue jobs.

## 1.1.6 — AMINAZADI

- Excluded metadata sidecars from sweeper audio candidates.
- Reported empty WAV recordings before invoking the GSM encoder, while preserving the source for diagnosis.

## 1.1.5 — AMINAZADI

- Fixed import rollback caused by regular-expression backslashes under `INI_SCANNER_RAW`.
- Added Base64-safe storage for endpoints, paths, secrets, and regular-expression settings.
- Changed parse-back validation to load the generated file through the production configuration codec.
- Added deployed-engine checksum verification to prevent an old runtime from restarting after upgrade.

## 1.1.4 — AMINAZADI

- Replaced modern SQLite UPSERT syntax with transactions compatible with older FreePBX SQLite libraries.
- Fixed uploads stopping immediately after the `Starting upload` log entry.
- Added destination and direction recovery for existing inbound recording sidecars.
- Added `CDR(dst)` and `FROM_DID` capture for future inbound recordings.

## 1.1.3 — AMINAZADI

- Fixed missing GSM encoder executable permissions in the FreePBX lifecycle installation path.
- Added import-time permission repair and deployed-runtime GSM encoder validation.

## 1.1.2 — AMINAZADI

- Added fail-safe migration for an already-patched FreePBX core when a verified legacy rollback backup exists.
- Kept unknown, partial, or mismatched core states fail-closed before installation mutation.

## 1.1.1 — AMINAZADI

- Added mandatory, verified pre-installation backups for CLI and FreePBX lifecycle installs.
- Added a checksum-verified restore helper with a fixed managed-path allowlist.
- Documented manual backup, verification, and rollback procedures.

## 1.1.0 — AMINAZADI

- Added versioned JSON import with masked preview, online validation, atomic apply, and rollback.
- Added explicit GZIP, ZIP, and AES-256 ZIP transports with backward-compatible defaults.
- Added durable credit blocking, collision-safe queue identifiers, metadata sidecars, dead-letter manifests, and uploaded-only retention.
- Added PHP 7.4 polyfills, dependency checks, secret-safe configuration encoding, queue status visibility, and pinned binary release verification.
