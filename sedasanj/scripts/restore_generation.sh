#!/usr/bin/env bash
# Restore a signed backup only into fresh PostgreSQL and MinIO volumes.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/backup_lib.sh"

VERIFY_ONLY=0
if [ "${1:-}" = --verify-only ]; then VERIFY_ONLY=1; shift; fi
[ $# = 1 ] && [ -f "$1" ] || die "usage: restore_generation.sh [--verify-only] <snapshot.gzip>"

umask 077
STARTED="$(date +%s)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
python3 "${SCRIPT_DIR}/backup_bundle.py" unpack "$1" "${WORK}/generation" \
  --limit "${BACKUP_RESTORE_MAX_BYTES:-2199023255552}"
SRC="${WORK}/generation"
[ -s "${SRC}/secrets/env" ] && [ -s "${SRC}/secrets/roles.sql" ] \
  || die "snapshot lacks deployment recovery settings"
if [ "${VERIFY_ONLY}" = 1 ]; then
  log "signed snapshot and every payload verified"
  exit 0
fi

PROJECT="${COMPOSE_PROJECT_NAME:-}"
[[ "${PROJECT}" =~ ^sedasanj-restore-[a-z0-9][a-z0-9-]{0,39}$ ]] \
  || die "set COMPOSE_PROJECT_NAME to a new sedasanj-restore-<name> project"
export POSTGRES_VOLUME_NAME="${PROJECT}_pgdata"
export MINIO_VOLUME_NAME="${PROJECT}_miniodata"
export MODULE_RELEASE_SIGNING_VOLUME_NAME="${PROJECT}_module-release-signing"
export PUBLISH_ADDRESS=127.0.0.1
export MINIO_API_PORT="${BACKUP_RESTORE_MINIO_PORT:-19000}"
docker compose config --format json | python3 -c '
import json, os, sys
config = json.load(sys.stdin)
expected = {
    "pgdata": os.environ["POSTGRES_VOLUME_NAME"],
    "miniodata": os.environ["MINIO_VOLUME_NAME"],
    "module-release-signing": os.environ["MODULE_RELEASE_SIGNING_VOLUME_NAME"],
}
for label, name in expected.items():
    volume = config.get("volumes", {}).get(label, {})
    if volume.get("name") != name or volume.get("external") or volume.get("driver_opts"):
        sys.exit("Restore requires isolated, project-owned volumes")
for service, target, label in (
    ("postgres", "/var/lib/postgresql/data", "pgdata"),
    ("minio", "/data", "miniodata"),
    ("api", "/module-release-signing", "module-release-signing"),
):
    mounts = [mount for mount in config["services"][service]["volumes"] if mount["target"] == target]
    if len(mounts) != 1 or mounts[0]["type"] != "volume" or mounts[0]["source"] != label:
        sys.exit("Restore requires isolated, project-owned mounts")
'
[ -z "$(docker compose ps -aq)" ] || die "choose a project with no existing containers"
for volume in "${POSTGRES_VOLUME_NAME}" "${MINIO_VOLUME_NAME}" "${MODULE_RELEASE_SIGNING_VOLUME_NAME}"; do
  if docker volume inspect "${volume}" >/dev/null 2>&1; then
    die "choose a project with fresh database, object and signing volumes"
  fi
done

log "starting only PostgreSQL and MinIO in ${PROJECT}"
docker compose up -d --wait --no-deps postgres minio
verify_dump_file "${SRC}/cbi.dump"
shopt -s nullglob
tenant_dumps=("${SRC}"/tenants/*.dump)
for dump in "${tenant_dumps[@]}"; do
  db="$(basename "${dump}" .dump)"
  [[ "${db}" =~ ^cbi_tenant_[0-9a-f]{32}$ ]] || die "invalid tenant database name"
  verify_dump_file "${dump}"
done

restore_database() {
  local db="$1" dump="$2"
  docker compose exec -T postgres pg_restore -U cbi -d "${db}" \
    --no-owner --no-acl --exit-on-error --single-transaction < "${dump}"
}

log "restoring control database"
restore_database cbi "${SRC}/cbi.dump"
docker compose exec -T postgres sh /docker-entrypoint-initdb.d/10-app-role.sh </dev/null

for dump in "${tenant_dumps[@]}"; do
  db="$(basename "${dump}" .dump)"
  log "restoring tenant database ${db}"
  grep -E "^(CREATE|ALTER) ROLE ${db}_app( |;)" "${SRC}/secrets/roles.sql" \
    | docker compose exec -T postgres psql -U cbi -d postgres -v ON_ERROR_STOP=1 -q >/dev/null
  psql_admin -c "CREATE DATABASE ${db} ENCODING 'UTF8' TEMPLATE template0"
  restore_database "${db}" "${dump}"
  tenant_grants_sql "${db}" \
    | docker compose exec -T postgres psql -U cbi -d "${db}" -v ON_ERROR_STOP=1 -q
  identity="$(docker compose exec -T postgres psql -U cbi -d "${db}" -v ON_ERROR_STOP=1 -qAt \
    -c "SELECT replace(tenant_id::text, '-', '') FROM tenant_identity" </dev/null)"
  [ "cbi_tenant_${identity}" = "${db}" ] || die "restored tenant identity does not match its database"
done

for dump in "${tenant_dumps[@]}"; do
  verify_media_files "$(basename "${dump}" .dump)" "${SRC}/objects" "${WORK}/references" true
done
verify_media_files cbi "${SRC}/objects" "${WORK}/references" "${LEGACY_MEDIA_SCOPE}"

log "restoring the generation's object inventory"
mkdir -p "${SRC}/objects"
docker compose exec -T minio sh -ec '
  mc alias set restore http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  mc mb --ignore-existing restore/audio >/dev/null
' </dev/null

find "${SRC}/objects" -type f -print0 > "${WORK}/objects"
while IFS= read -r -d '' source; do
  key="${source#"${SRC}/objects/"}"
  expected="$(sha256_of "${source}")"
  docker compose exec -T minio bash -c '
    set -euo pipefail
    mc pipe "restore/audio/$1" >/dev/null
    actual=$(mc cat "restore/audio/$1" | sha256sum)
    [ "${actual%% *}" = "$2" ] || { echo "restored object checksum differs" >&2; exit 1; }
  ' bash "${key}" "${expected}" < "${source}"
done < "${WORK}/objects"

# The staged configuration needs the original keys and the new project's deployment settings.
recovered_env="${BACKUP_RECOVERED_ENV_FILE:-${ENV_FILE}.${PROJECT}.from-backup}"
(set -o noclobber; cat "${SRC}/secrets/env" > "${recovered_env}") \
  || die "choose an unused BACKUP_RECOVERED_ENV_FILE path"
if [ -s "${SRC}/secrets/module-release-signing.seed" ]; then
  docker compose run --rm --no-deps -T --entrypoint sh api -c '
    umask 077
    mkdir -p /module-release-signing
    cat > /module-release-signing/private.seed
  ' < "${SRC}/secrets/module-release-signing.seed"
fi

log "restored and verified ${PROJECT}; writers remain stopped"
elapsed="$(( $(date +%s) - STARTED ))"
stamp="$(sed -n 's/^stamp=//p' "${SRC}/MANIFEST")"
printf 'Snapshot %s restored in %s seconds\n' "${stamp}" "${elapsed}"
if [ -n "${BACKUP_DRILL_REPORT:-}" ]; then
  report="$(mktemp "${BACKUP_DRILL_REPORT}.XXXXXXXX")"
  printf 'stamp=%s\nrestored_at=%s\nduration_seconds=%s\n' \
    "${stamp}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${elapsed}" > "${report}"
  mv "${report}" "${BACKUP_DRILL_REPORT}"
fi
echo "Review ${recovered_env} and the isolated volumes before performing a controlled cutover."
