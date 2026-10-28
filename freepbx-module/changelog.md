# Changelog

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
