# Seda Sanj FreePBX Module 1.3.1

Voicemail upload is disabled by default. Enable it in **Admin > Seda Sanj > Voicemail** after confirming the Asterisk service account can read `/var/spool/asterisk/voicemail`. The sweeper reads message metadata and audio without modifying mailbox files, skips `tmp`, and uploads only complete messages older than the recording settle interval. Existing messages are ignored on first activation unless backfill is explicitly enabled. GSM and wav49 inputs are converted to mono 8 kHz PCM in the private pending spool before upload; original voicemail files are never renamed, moved, or deleted.

Voicemail uses `POST /v1/ingest/voicemails`, shares the recording upload format and retry queue, and consumes no processing credit. To inspect or run one scan manually, use `php /var/lib/asterisk-recording-uploader/bin/sweeper.php --voicemail --once` or add `--report` for a dry run.

Inbound answered-extension attribution reads the completed FreePBX CDR by the recording's exact Asterisk unique ID. Only one unambiguous answered PJSIP/SIP numeric peer is sent as `agent_extension`; otherwise the field stays empty. The CDR may take several seconds to finalize, so the post-processing hook retries briefly. Existing calls already uploaded before this release are not modified.

Supported environments: FreePBX 16/17, PHP 7.4 through PHP 8.x, and Linux x86_64/aarch64.

## Install or upgrade

1. Extract the release ZIP and run `sudo ./recuploader/install.sh`.
2. The installer creates a mandatory backup before its first mutation. It aborts if the backup cannot be completed or verified.
3. Open **Admin > Seda Sanj > Import Configuration**.
4. Upload `sedasanj-freepbx-config.json`, review the masked preview, and apply it.
5. Place inbound and outbound canary calls and monitor the queue, disk space, and ingest status.

## Installation backup and restore

Every CLI or `fwconsole` installation creates a timestamped, root-only backup under `/var/backups/sedasanj-recuploader/`. The backup includes the existing module, the verified `callrecording` core file, managed Asterisk dialplan files, systemd and sudoers files, uploader binaries, configuration, state, queue, and logs. It also contains a manifest, present/absent path lists, and SHA-256 checksums.

To create the same backup manually before uploading or extracting a new release:

```bash
sudo ./recuploader/backup-installation.sh
```

Keep the printed backup directory. To verify it:

```bash
sudo sh -c 'cd /var/backups/sedasanj-recuploader/BACKUP_DIRECTORY && sha256sum -c SHA256SUMS'
```

To restore the exact pre-installation state, use the restore helper from the extracted release:

```bash
sudo ./recuploader/restore-installation-backup.sh /var/backups/sedasanj-recuploader/BACKUP_DIRECTORY
```

The restore helper verifies every checksum, rejects paths outside the fixed managed-path allowlist, stops the uploader, restores files and permissions, reloads FreePBX, and returns the service to its previous active/stopped state. Copy the backup off the PBX before production installation if the host itself is not covered by another backup system.

Upgrades from older module releases are supported when `callrecording/functions.inc.php` is already patched but the new rollback state is absent. The installer accepts that state only when a legacy `.orig` or state-directory backup reproduces the installed patched file exactly; it then imports the verified original into the new checksum-protected rollback state. Any mismatch aborts before installation changes.

The installer sets executable permissions on all bundled encoder directories, including GSM, in both the FreePBX module tree and the deployed runtime tree. Import validation also repairs a missing executable bit when permitted and checks the deployed runtime encoder as a fallback.

SQLite persistence uses legacy-compatible `INSERT OR IGNORE` plus `UPDATE` transactions rather than UPSERT syntax, so FreePBX distributions with older SQLite libraries can record state and queue jobs. Existing stereo recordings that stopped immediately after `Starting upload` remain in the monitor tree and are recovered by the first sweep after upgrade. Metadata for older inbound sidecars is completed from the stable FreePBX recording filename when destination or direction was not recorded.

Free-form configuration strings are stored in Base64 companion fields before PHP parses the INI file. This preserves regular-expression backslashes under `INI_SCANNER_RAW` and prevents parse-back mismatches. Installation verifies that the deployed runtime engine matches the module release before restarting the service.

The importer accepts only schema version 1 profiles targeted at `freepbx-module`. It validates the file, runtime, paths, regular expressions, binaries, API key, transport, and optional ZIP password before offering a ten-minute one-time apply token. Apply uses a parse-checked atomic configuration replacement and rolls back the KV store, file, and service when restart verification fails.

## Automatic updates

From 1.3.0 the module page checks the Seda Sanj API (`GET /v1/ingest/module/updates`, using the configured endpoint and API key) on every visit and shows a banner when a newer release is published. **Update** downloads the release, verifies its SHA-256 and Ed25519 signature, and hands it to the root-owned helper `/usr/local/sbin/sedasanj-recuploader-update` (allowed for the `asterisk` user in `/etc/sudoers.d/asterisk-recording-uploader`). The helper re-verifies the package against `/etc/sedasanj-recuploader-update/release-signing.pub`, takes the standard installation backup, swaps `/var/www/html/admin/modules/recuploader` (the old tree is kept as `.recuploader.prev`), runs `fwconsole ma install recuploader`, `fwconsole chown` and `fwconsole reload`, checks the service and registered version, and reports the result. Any failure after the swap restores the previous tree and backup and re-registers the previous version. Progress and logs are in `/var/lib/sedasanj-recuploader-update/jobs/<job>/`; the last two jobs are kept.

Requirements: the PHP sodium extension (`php-sodium`), and a root install of 1.3.0 (install.sh or `fwconsole ma install`) so the helper, key and sudoers entry exist. Installing only through the Module Admin GUI cannot provision them; the page then explains why automatic update is unavailable.

### Release signing

Releases are signed by the API with a detached Ed25519 signature over the lowercase SHA-256 hex digest of the release zip. Generate the key pair once, on a trusted machine:

```bash
openssl genpkey -algorithm ed25519 -outform DER -out release-signing.der
```

```bash
tail -c 32 release-signing.der | base64
```

```bash
openssl pkey -inform DER -in release-signing.der -pubout -outform DER | tail -c 32 | base64
```

The first base64 value (the 32-byte private seed) goes only into the API's `MODULE_RELEASE_SIGNING_KEY` environment variable; the second (the public key) replaces the placeholder line in `assets/release-signing.pub` before building a release. Delete `release-signing.der` once both are stored safely. A placeholder or malformed key disables automatic updates.

## Transport and local archive

`upload.format` controls the payload accepted by the API key: `gzip`, unencrypted `zip`, or AES-256 `zip` when `general.archive_password` is configured. `archive.format` is separate and controls only the local mono copy; its default is `gsm`.

HTTP 402 responses remain in `blocked_credit`, do not consume an attempt, and retry after `queue.credit_retry_seconds`. Pending and failed recordings are never removed by retention. Only successfully uploaded files in the configured `uploaded` directory are removed after `state.retention_days`.

## Uninstall

Run `sudo ./recuploader/uninstall.sh` to keep config, state, queue, and logs, or add `--purge` to remove them. Purge deletes pending and failed recordings and must only be used after a backup.
