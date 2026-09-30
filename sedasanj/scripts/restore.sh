#!/usr/bin/env bash
# Restore drill (phase 9). Usage: ./restore.sh /srv/backup/20260819T020000Z
set -euo pipefail

SRC="${1:?usage: restore.sh <backup-dir>}"
test -f "${SRC}/cbi.dump"

echo "==> stopping writers"
docker compose stop api worker-asr worker-llm worker-notify

echo "==> restoring postgres (drops and recreates public schema)"
docker compose exec -T postgres psql -U cbi -d cbi -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec -T postgres pg_restore -U cbi -d cbi --no-owner < "${SRC}/cbi.dump"

echo "==> restoring audio objects"
docker compose exec -T minio sh -lc "
  mc alias set local http://127.0.0.1:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null &&
  mc mirror --overwrite --quiet /data-backup/$(basename "${SRC}") local/audio
"

echo "==> starting services"
docker compose up -d api worker-asr worker-llm worker-notify

echo "verify: curl -fsS https://\${API_DOMAIN}/healthz && check /v1/calls counts"
