#!/usr/bin/env bash
# Full backup: control database, every tenant database, MinIO audio, and an encrypted secrets bundle.
#
# Layout of one backup (BACKUP_DIR/<UTC stamp>/):
#   cbi.dump                 control database (pg_dump -Fc)
#   tenants/<db>.dump        one dump per cbi_tenant_<uuid> database
#   secrets.tar.enc          AES-256 encrypted: deploy/.env, DB roles, module release signing seed
#   audio.manifest           object listing of the audio bucket at backup time
#   SHA256SUMS, MANIFEST     integrity data; a backup without them is not trusted by restore
# The audio bucket itself is mirrored incrementally into BACKUP_DIR/audio-mirror (host disk).
#
# Environment:
#   BACKUP_DIR                  destination root (default /srv/backup)
#   BACKUP_PASSPHRASE_FILE      file holding the secrets-bundle passphrase (required unless BACKUP_SKIP_SECRETS=1)
#   BACKUP_OFFSITE_TARGET       rsync destination for the whole BACKUP_DIR, e.g. backup@host:/srv/cbi or a mounted path
#   BACKUP_RETENTION_DAYS       delete complete backups older than this (default 14) ...
#   BACKUP_KEEP_LAST            ... but never leave fewer than this many complete backups (default 7)
#   BACKUP_SKIP_AUDIO=1         skip the MinIO mirror (used by the pre-restore snapshot)
#   BACKUP_SKIP_SECRETS=1       skip the encrypted secrets bundle (not recommended)
# Run from anywhere; the script switches to deploy/.
set -euo pipefail
# shellcheck source=backup_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/backup_lib.sh"

BACKUP_ROOT="${BACKUP_DIR:-/srv/backup}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
KEEP_LAST="${BACKUP_KEEP_LAST:-7}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL="${BACKUP_ROOT}/${STAMP}"
WORK="${FINAL}.partial"
LOCK="${BACKUP_ROOT}/.backup.lock"

case "${KEEP_LAST}" in ''|*[!0-9]*) die "BACKUP_KEEP_LAST must be a non-negative integer" ;; esac
case "${RETENTION_DAYS}" in ''|*[!0-9]*) die "BACKUP_RETENTION_DAYS must be a non-negative integer" ;; esac
if [ "${BACKUP_SKIP_SECRETS:-0}" != 1 ]; then
  [ -n "${BACKUP_PASSPHRASE_FILE:-}" ] && [ -s "${BACKUP_PASSPHRASE_FILE}" ] \
    || die "set BACKUP_PASSPHRASE_FILE to a non-empty passphrase file (or BACKUP_SKIP_SECRETS=1)"
fi

umask 077
mkdir -p "${BACKUP_ROOT}"
if ! mkdir "${LOCK}" 2>/dev/null; then
  die "another backup is running (remove ${LOCK} if it is stale)"
fi
TMPFILES="$(mktemp -d)"
cleanup() {
  rm -rf "${LOCK}" "${TMPFILES}"
  # An interrupted run leaves only the .partial directory, which is never used for restore.
}
trap cleanup EXIT
mkdir -p "${WORK}/tenants"

dump_database() {
  local db="$1" out="$2" tmp="$2.tmp"
  shift 2
  docker compose exec -T postgres pg_dump -U cbi -d "${db}" -Fc "$@" </dev/null > "${tmp}"
  [ -s "${tmp}" ] || die "empty dump for ${db}"
  verify_dump_file "${tmp}"
  mv "${tmp}" "${out}"
}

log "control database"
dump_database cbi "${WORK}/cbi.dump"

log "tenant databases"
TENANT_DBS=()
while IFS= read -r db; do
  [ -n "${db}" ] && TENANT_DBS+=("${db}")
done < <(psql_admin -c "SELECT datname FROM pg_database WHERE datname LIKE 'cbi\_tenant\_%' AND NOT datname LIKE '%\_pre%' AND NOT datname LIKE '%\_new%' ORDER BY 1")
for db in "${TENANT_DBS[@]+"${TENANT_DBS[@]}"}"; do
  echo "    ${db}"
  dump_database "${db}" "${WORK}/tenants/${db}.dump" --no-owner --no-acl
done
echo "    ${#TENANT_DBS[@]} tenant database(s)"

log "audio objects"
if [ "${BACKUP_SKIP_AUDIO:-0}" = 1 ]; then
  echo "    skipped"
else
  MIRROR="${BACKUP_ROOT}/audio-mirror"
  mkdir -p "${MIRROR}"
  # Mirror straight to the host so it survives container recreation. No --remove: objects deleted
  # by retention stay recoverable until the mirror is pruned by the operator.
  docker compose run --rm --no-deps -T -v "${MIRROR}:/backup-out" --entrypoint sh minio -c '
    mc alias set src http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null &&
    mc mirror --overwrite --quiet src/audio /backup-out &&
    mc ls --recursive src/audio
  ' </dev/null > "${WORK}/audio.manifest"
fi

if [ "${BACKUP_SKIP_SECRETS:-0}" != 1 ]; then
  log "encrypted secrets bundle"
  SECRETS="${TMPFILES}/secrets"
  mkdir -p "${SECRETS}"
  [ -f "${ENV_FILE}" ] || die "${ENV_FILE} not found in $(pwd); it holds the keys that decrypt tenant data"
  cp "${ENV_FILE}" "${SECRETS}/env"
  docker compose exec -T postgres pg_dumpall -U cbi --roles-only </dev/null > "${SECRETS}/roles.sql"
  seed_found=0
  if docker compose exec -T api test -f /module-release-signing/private.seed </dev/null 2>/dev/null; then
    docker compose exec -T api cat /module-release-signing/private.seed </dev/null > "${SECRETS}/module-release-signing.seed"
    seed_found=1
  elif docker compose run --rm --no-deps -T --entrypoint sh api -c 'test -f /module-release-signing/private.seed' </dev/null 2>/dev/null; then
    docker compose run --rm --no-deps -T --entrypoint sh api -c 'cat /module-release-signing/private.seed' </dev/null > "${SECRETS}/module-release-signing.seed"
    seed_found=1
  fi
  [ "${seed_found}" = 1 ] || warn "no module release signing seed found (covered by MODULE_RELEASE_SIGNING_KEY in .env if set)"
  tar -C "${SECRETS}" -cf - . \
    | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass "file:${BACKUP_PASSPHRASE_FILE}" \
      -out "${WORK}/secrets.tar.enc.tmp"
  mv "${WORK}/secrets.tar.enc.tmp" "${WORK}/secrets.tar.enc"
  # Prove the bundle can be decrypted before the backup is declared good.
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass "file:${BACKUP_PASSPHRASE_FILE}" \
    -in "${WORK}/secrets.tar.enc" | tar -tf - >/dev/null || die "secrets bundle failed decrypt check"
fi

log "checksums and manifest"
{
  echo "stamp=${STAMP}"
  echo "tenant_databases=${#TENANT_DBS[@]}"
  echo "created_by=$(id -un)@$(hostname)"
} > "${WORK}/MANIFEST"
(
  cd "${WORK}"
  for f in cbi.dump tenants/*.dump secrets.tar.enc audio.manifest MANIFEST; do
    [ -f "${f}" ] || continue
    printf '%s  %s\n' "$(sha256_of "${f}")" "${f}"
  done > SHA256SUMS
)
verify_checksums "${WORK}"

mv "${WORK}" "${FINAL}"
date -u +%Y-%m-%dT%H:%M:%SZ > "${BACKUP_ROOT}/.last_success"

log "prune (older than ${RETENTION_DAYS} days, always keeping the newest ${KEEP_LAST})"
COMPLETE=()
while IFS= read -r d; do
  COMPLETE+=("${d}")
done < <(find "${BACKUP_ROOT}" -maxdepth 1 -mindepth 1 -type d -name '[0-9]*T[0-9]*Z' | sort -r)
index=0
for d in "${COMPLETE[@]}"; do
  index=$((index + 1))
  [ "${index}" -gt "${KEEP_LAST}" ] || continue
  if [ -n "$(find "${d}" -maxdepth 0 -mtime "+${RETENTION_DAYS}")" ]; then
    echo "    removing ${d}"
    rm -rf "${d}"
  fi
done
find "${BACKUP_ROOT}" -maxdepth 1 -mindepth 1 -type d -name '*.partial' -mtime +1 -exec rm -rf {} +

if [ -n "${BACKUP_OFFSITE_TARGET:-}" ]; then
  log "off-host copy to ${BACKUP_OFFSITE_TARGET}"
  rsync -a --exclude '.backup.lock' "${BACKUP_ROOT}/" "${BACKUP_OFFSITE_TARGET%/}/" \
    || die "off-host copy failed; the local backup ${FINAL} is intact"
else
  warn "BACKUP_OFFSITE_TARGET is not set: this backup exists only on this host"
fi

echo "backup complete: ${FINAL}"
