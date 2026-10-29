---
name: sedasanj-backup-restore
description: Plan, verify and drill backups and restores for SedaSanj (databases, MinIO, keys) and the FreePBX module install backup. Use before migrations, updates or any destructive operation.
---

# Backup and restore

## What exists (verified)

- Server: `sedasanj/scripts/backup.sh` (pg_dump `-Fc` of database `cbi`, MinIO `mc mirror`, copy of the module signing seed, pruning by `BACKUP_RETENTION_DAYS`, default 14) and `sedasanj/scripts/restore.sh`.
- **Hazard:** `restore.sh` runs `DROP SCHEMA public CASCADE` on the live database after stopping writers. Do not run it on production without a verified fresh backup and explicit approval. Hardening (new database or `--clean --if-exists --single-transaction --exit-on-error`, `--yes`, pre-restore snapshot) is planned work.
- Tenant databases and tenant backups: `sedasanj/docs/tenant-databases.md`, `app/services/tenant_backups.py`.
- FreePBX module: `freepbx-module/backup-installation.sh` and `restore-installation-backup.sh` (timestamped root-only backup under `/var/backups/sedasanj-recuploader/` with manifest and SHA-256 checksums; restore refuses paths outside its allowlist).

## Must be backed up (plan)

Control DB and every tenant DB; MinIO audio; keys: `TENANT_DATABASE_MASTER_KEY`, `PLATFORM_SECRETS_KEY`, `JWT_SECRET`, `API_KEY_PEPPER`, module signing seed. Without these keys the DB backups may be undecryptable. Store key backups encrypted and off-host. Never paste key values into chat, logs or commits.

## Rules

1. No root/destructive operation or migration without a backup you verified (`pg_restore --list`, checksum, test restore into a scratch database).
2. Write backups to a temp name then rename; keep a minimum number of copies when pruning.
3. Drill a full restore periodically and record the result.
4. Before updating the module on a PBX, confirm the installation backup exists and is copied off-host.
