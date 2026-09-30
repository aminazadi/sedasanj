#!/usr/bin/env bash
# Nightly backup: Postgres logical dump + MinIO mirror. Run from deploy/.
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR:-/srv/backup}/${STAMP}"
mkdir -p "${DEST}"

echo "==> postgres dump"
docker compose exec -T postgres pg_dump -U cbi -d cbi -Fc > "${DEST}/cbi.dump"

echo "==> minio mirror"
docker compose exec -T minio sh -lc "
  mc alias set local http://127.0.0.1:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null &&
  mc mirror --overwrite --quiet local/audio /data-backup/${STAMP}
"

echo "==> prune backups older than ${BACKUP_RETENTION_DAYS:-14} days"
find "${BACKUP_DIR:-/srv/backup}" -maxdepth 1 -mindepth 1 -type d \
  -mtime "+${BACKUP_RETENTION_DAYS:-14}" -exec rm -rf {} +

echo "backup complete: ${DEST}"
