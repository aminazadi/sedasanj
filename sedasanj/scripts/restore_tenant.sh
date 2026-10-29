#!/usr/bin/env bash
# Restore ONE tenant database from a backup made by backup.sh.
# Usage: restore_tenant.sh [--yes] [--no-stop] [--roles-file FILE] <backup-dir> <tenant-uuid|cbi_tenant_hex>
#
# The dump is restored into a fresh database and swapped in by rename, so a failed restore never
# touches the live data; the replaced database is kept as <db>_pre<stamp> for rollback.
# The tenant's login role must already exist (it does on the original server). On a rebuilt server pass
# --roles-file with the roles.sql taken from the decrypted secrets bundle (restore.sh does this for you).
set -euo pipefail
# shellcheck source=backup_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/backup_lib.sh"

YES=0
STOP=1
ROLES_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --no-stop) STOP=0 ;;
    --roles-file) shift; ROLES_FILE="${1:?--roles-file needs a path}" ;;
    --) shift; break ;;
    -*) die "unknown option: $1" ;;
    *) break ;;
  esac
  shift
done
[ $# -eq 2 ] || die "usage: restore_tenant.sh [--yes] [--no-stop] [--roles-file FILE] <backup-dir> <tenant-uuid>"
SRC="${1%/}"
DB="$(tenant_db_name "$2")"
ROLE="${DB}_app"
DUMP="${SRC}/tenants/${DB}.dump"
[ -f "${DUMP}" ] || die "no dump for ${DB} in ${SRC}/tenants"

log "verifying backup"
verify_checksums "${SRC}"
verify_dump_file "${DUMP}"

if [ "${YES}" != 1 ]; then
  echo "This replaces tenant database ${DB} with the copy from $(basename "${SRC}")."
  echo "Tenant data written after that backup will be lost (the replaced database is kept as ${DB}_pre<stamp>)."
  printf 'Type the tenant database name to continue: '
  read -r answer
  [ "${answer}" = "${DB}" ] || die "confirmation did not match; nothing changed"
fi

role_exists="$(psql_admin -c "SELECT 1 FROM pg_roles WHERE rolname = '${ROLE}'")"
if [ -z "${role_exists}" ]; then
  [ -n "${ROLES_FILE}" ] || die "role ${ROLE} does not exist; pass --roles-file (from the secrets bundle)"
  log "recreating role ${ROLE}"
  grep -E "^(CREATE|ALTER) ROLE ${ROLE}( |;)" "${ROLES_FILE}" \
    | docker compose exec -T postgres psql -U cbi -d postgres -v ON_ERROR_STOP=1 -q
fi

STAMP="$(date -u +%y%m%d%H%M%S)"
if [ "${STOP}" = 1 ]; then
  stop_writers
fi

swap_restore_database "${DB}" "${DUMP}" "${STAMP}"

log "re-applying tenant grants"
tenant_grants_sql "${DB}" | docker compose exec -T postgres psql -U cbi -d "${DB}" -v ON_ERROR_STOP=1 -q

COUNT="$(docker compose exec -T postgres psql -U cbi -d "${DB}" -qAt -c 'SELECT count(*) FROM tenant_identity' </dev/null)"
[ "${COUNT}" = 1 ] || die "tenant_identity has ${COUNT} rows after restore; investigate before starting services"

if [ "${STOP}" = 1 ]; then
  start_writers
fi
echo "tenant ${DB} restored. Rollback copy: ${DB}_pre${STAMP} (DROP DATABASE it once verified)."
