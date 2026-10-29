#!/usr/bin/env bash
# Full restore from a backup made by backup.sh (also the monthly restore drill).
# Usage: restore.sh [--yes] [--skip-snapshot] [--skip-audio] [--skip-tenants]
#                   [--restore-secrets] [--audio-dir DIR] <backup-dir>
#
#   * checksums and every dump are verified before anything is stopped
#   * all writers (api, every worker) are stopped
#   * a pre-restore snapshot of the current state is taken (BACKUP_DIR/pre-restore), unless --skip-snapshot
#   * the control database and each tenant database are restored into FRESH databases and swapped in by
#     rename; the previous ones stay as <db>_pre<stamp>. pg_restore runs with --exit-on-error and
#     --single-transaction, so any error aborts without touching live data
#   * the cbi_app role/grants are re-applied by re-running postgres/init/10-app-role.sh
#   * --restore-secrets writes deploy/.env.from-backup and the module signing seed; it never overwrites .env
# Needs BACKUP_PASSPHRASE_FILE to read the secrets bundle (roles, signing seed).
set -euo pipefail
# shellcheck source=backup_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/backup_lib.sh"

YES=0; SNAPSHOT=1; AUDIO=1; TENANTS=1; SECRETS=0; AUDIO_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --skip-snapshot) SNAPSHOT=0 ;;
    --skip-audio) AUDIO=0 ;;
    --skip-tenants) TENANTS=0 ;;
    --restore-secrets) SECRETS=1 ;;
    --audio-dir) shift; AUDIO_DIR="${1:?--audio-dir needs a path}" ;;
    --) shift; break ;;
    -*) die "unknown option: $1" ;;
    *) break ;;
  esac
  shift
done
[ $# -eq 1 ] || die "usage: restore.sh [options] <backup-dir>"
SRC="${1%/}"
SRC="$(cd "${SRC}" && pwd)"
BACKUP_ROOT="${BACKUP_DIR:-$(dirname "${SRC}")}"
AUDIO_DIR="${AUDIO_DIR:-${BACKUP_ROOT}/audio-mirror}"
STAMP="$(date -u +%y%m%d%H%M%S)"

umask 077
TMPFILES="$(mktemp -d)"
trap 'rm -rf "${TMPFILES}"' EXIT

log "verifying backup ${SRC}"
[ -f "${SRC}/cbi.dump" ] || die "${SRC}/cbi.dump not found"
verify_checksums "${SRC}"
verify_dump_file "${SRC}/cbi.dump"
TENANT_DUMPS=()
if [ "${TENANTS}" = 1 ] && [ -d "${SRC}/tenants" ]; then
  for f in "${SRC}"/tenants/*.dump; do
    [ -f "${f}" ] || continue
    verify_dump_file "${f}"
    TENANT_DUMPS+=("${f}")
  done
fi
[ "${AUDIO}" = 0 ] || [ -d "${AUDIO_DIR}" ] || die "audio mirror ${AUDIO_DIR} not found (use --skip-audio or --audio-dir)"

ROLES_FILE=""
if [ -f "${SRC}/secrets.tar.enc" ]; then
  [ -n "${BACKUP_PASSPHRASE_FILE:-}" ] && [ -s "${BACKUP_PASSPHRASE_FILE}" ] \
    || die "set BACKUP_PASSPHRASE_FILE so the secrets bundle (roles, signing seed) can be read"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass "file:${BACKUP_PASSPHRASE_FILE}" \
    -in "${SRC}/secrets.tar.enc" | tar -C "${TMPFILES}" -xf - || die "cannot decrypt secrets bundle (wrong passphrase?)"
  ROLES_FILE="${TMPFILES}/roles.sql"
fi
if [ "${#TENANT_DUMPS[@]}" -gt 0 ] && [ -z "${ROLES_FILE}" ]; then
  warn "no secrets bundle: tenant roles must already exist on this server"
fi

echo "About to restore: control DB + ${#TENANT_DUMPS[@]} tenant DB(s)$([ "${AUDIO}" = 1 ] && echo " + audio from ${AUDIO_DIR}") from $(basename "${SRC}")."
echo "All writers (api and workers) will be stopped. Current databases are kept as *_pre${STAMP}."
if [ "${YES}" != 1 ]; then
  printf 'Type RESTORE %s to continue: ' "$(basename "${SRC}")"
  read -r answer
  [ "${answer}" = "RESTORE $(basename "${SRC}")" ] || die "confirmation did not match; nothing changed"
fi

stop_writers

if [ "${SNAPSHOT}" = 1 ]; then
  log "pre-restore snapshot"
  BACKUP_DIR="${BACKUP_ROOT}/pre-restore" BACKUP_SKIP_AUDIO=1 BACKUP_OFFSITE_TARGET="" \
    BACKUP_KEEP_LAST="${BACKUP_KEEP_LAST:-7}" "${SCRIPT_DIR}/backup.sh" \
    || die "pre-restore snapshot failed; nothing was restored (use --skip-snapshot to override)"
fi

if [ -n "${ROLES_FILE}" ] && [ "${#TENANT_DUMPS[@]}" -gt 0 ]; then
  log "ensuring tenant roles exist"
  # CREATE fails harmlessly for roles that already exist; ALTER re-applies attributes and password.
  grep -E '^(CREATE|ALTER) ROLE cbi_tenant_[0-9a-f]+_app( |;)' "${ROLES_FILE}" \
    | docker compose exec -T postgres psql -U cbi -d postgres -q || true
fi

swap_restore_database cbi "${SRC}/cbi.dump" "${STAMP}"

log "re-applying cbi_app role and grants"
docker compose up -d postgres
docker compose exec -T postgres sh /docker-entrypoint-initdb.d/10-app-role.sh </dev/null

for dump in "${TENANT_DUMPS[@]+"${TENANT_DUMPS[@]}"}"; do
  name="$(basename "${dump}" .dump)"
  "${SCRIPT_DIR}/restore_tenant.sh" --yes --no-stop "${SRC}" "${name}"
done

if [ "${AUDIO}" = 1 ]; then
  log "restoring audio objects from ${AUDIO_DIR}"
  docker compose up -d minio
  docker compose run --rm --no-deps -T -v "${AUDIO_DIR}:/restore-in:ro" --entrypoint sh minio -c '
    mc alias set dst http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null &&
    (mc mb --ignore-existing dst/audio >/dev/null) &&
    mc mirror --overwrite --quiet /restore-in dst/audio
  ' </dev/null
fi

if [ "${SECRETS}" = 1 ]; then
  [ -f "${TMPFILES}/env" ] || die "--restore-secrets needs a secrets bundle"
  log "restoring secrets (review deploy/.env.from-backup and move it to .env yourself)"
  cp "${TMPFILES}/env" "${ENV_FILE}.from-backup"
  chmod 600 "${ENV_FILE}.from-backup"
  if [ -f "${TMPFILES}/module-release-signing.seed" ]; then
    docker compose run --rm --no-deps -T --entrypoint sh api -c '
      umask 077
      mkdir -p /module-release-signing
      cat > /module-release-signing/private.seed
    ' < "${TMPFILES}/module-release-signing.seed"
  fi
fi

start_writers

echo "restore complete. Verify: curl -fsS https://\${API_DOMAIN}/healthz, compare call counts, open one tenant dashboard."
echo "Rollback copies are the *_pre${STAMP} databases; drop them after verification."
