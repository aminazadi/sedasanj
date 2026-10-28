#!/usr/bin/env bash
# Nightly backup: Postgres logical dump, MinIO mirror, and release signing key. Run from deploy/.
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

echo "==> module release signing key"
if docker compose exec -T api test -f /module-release-signing/private.seed; then
  docker compose exec -T api cat /module-release-signing/private.seed > "${DEST}/module-release-signing.seed"
  chmod 600 "${DEST}/module-release-signing.seed"
fi

echo "==> prune backups older than ${BACKUP_RETENTION_DAYS:-14} days"
find "${BACKUP_DIR:-/srv/backup}" -maxdepth 1 -mindepth 1 -type d \
  -mtime "+${BACKUP_RETENTION_DAYS:-14}" -exec rm -rf {} +

echo "backup complete: ${DEST}"
