---
name: sedasanj-backup-restore
description: Plan, verify and drill backups and restores for SedaSanj (databases, MinIO, keys) and the FreePBX module install backup. Use before migrations, updates or any destructive operation.
---

# Backup and restore

## What exists (verified)

- Server (rewritten on branch `claude/strange-rhodes-0002c8`, commit `26ae510`; confirm it is merged before relying on it): `sedasanj/scripts/backup.sh` dumps the control DB and every `cbi_tenant_<uuid>` DB, mirrors MinIO audio to the host (`audio-mirror`), writes an AES-256 encrypted secrets bundle (`.env`, DB roles, module signing seed), verifies dumps with `pg_restore --list`, writes `SHA256SUMS`, uses temp-then-rename, keeps the newest `BACKUP_KEEP_LAST` backups when pruning, and can rsync off-host (`BACKUP_OFFSITE_TARGET`). Shared helpers: `backup_lib.sh`.
- Restore: `restore.sh` verifies checksums, asks for typed confirmation (or `--yes`), stops all writers, takes a pre-restore snapshot, restores into fresh databases with `--exit-on-error --single-transaction`, swaps by rename (old copy kept as `<db>_pre<stamp>`), re-runs `10-app-role.sh`. `restore_tenant.sh` restores one tenant. Never run either against production without a verified backup and explicit approval; drop `_pre` copies only after verification.
- Tenant databases and tenant backups: `sedasanj/docs/tenant-databases.md`, `app/services/tenant_backups.py`.
- FreePBX module: `freepbx-module/backup-installation.sh` and `restore-installation-backup.sh` (timestamped root-only backup under `/var/backups/sedasanj-recuploader/` with manifest and SHA-256 checksums; restore refuses paths outside its allowlist).

## Must be backed up (plan)

Control DB and every tenant DB; MinIO audio; keys: `TENANT_DATABASE_MASTER_KEY`, `PLATFORM_SECRETS_KEY`, `JWT_SECRET`, `API_KEY_PEPPER`, module signing seed. Without these keys the DB backups may be undecryptable. Store key backups encrypted and off-host. Never paste key values into chat, logs or commits.

## Rules

1. No root/destructive operation or migration without a backup you verified (`pg_restore --list`, checksum, test restore into a scratch database).
2. Write backups to a temp name then rename; keep a minimum number of copies when pruning.
3. Drill a full restore periodically and record the result.
4. Before updating the module on a PBX, confirm the installation backup exists and is copied off-host.
