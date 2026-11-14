#!/usr/bin/env bash
# Shared helpers for backup.sh, restore.sh and restore_tenant.sh. Source it; do not execute it.
# shellcheck shell=bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Scripts operate on the Compose project in deploy/. COMPOSE_FILE (standard Compose variable)
# overrides this, which is how the local drill runs against a scratch project.
if [ -z "${COMPOSE_FILE:-}" ]; then
  cd "${SCRIPT_DIR}/../deploy" || exit 1
fi
ENV_FILE="${ENV_FILE:-.env}"

log() { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# Verify every "<sha256>  <file>" line of SHA256SUMS inside a backup directory.
verify_checksums() {
  local dir="$1" line sum file actual
  [ -f "${dir}/SHA256SUMS" ] || die "${dir}/SHA256SUMS is missing; refusing to use an unverifiable backup"
  while IFS= read -r line; do
    [ -n "${line}" ] || continue
    sum="${line%% *}"
    file="${line#*  }"
    [ -f "${dir}/${file}" ] || die "checksum listed file is missing: ${file}"
    actual="$(sha256_of "${dir}/${file}")"
    [ "${sum}" = "${actual}" ] || die "checksum mismatch for ${file}"
  done < "${dir}/SHA256SUMS"
}

pg() { docker compose exec -T postgres "$@" </dev/null; }
psql_admin() { docker compose exec -T postgres psql -U cbi -d postgres -v ON_ERROR_STOP=1 -qAt "$@" </dev/null; }

# A dump is only trusted when pg_restore can read its table of contents.
verify_dump_file() {
  docker compose exec -T postgres pg_restore --list < "$1" >/dev/null 2>&1 \
    || die "pg_restore --list rejected $1"
}

# Only a tenant's active database owns its object references after dedicated cutover.
LEGACY_MEDIA_SCOPE="tenant_id NOT IN (SELECT tenant_id FROM tenant_database_registry WHERE status = 'ready')"
verify_media_files() {
  local db="$1" directory="$2" references="$3" condition="$4" key
  docker compose exec -T postgres psql -U cbi -d "${db}" -v ON_ERROR_STOP=1 -qAt -c "
    SELECT object_key FROM audio_objects
      WHERE deleted_at IS NULL AND (expires_at IS NULL OR expires_at > now()) AND (${condition})
    UNION
    SELECT storage_key FROM assistant_exports
      WHERE deleted_at IS NULL AND expires_at > now() AND (${condition})
  " </dev/null > "${references}"
  while IFS= read -r key; do
    case "${key}" in ''|/*|..|../*|*/../*|*/..) die "invalid media reference in ${db}" ;; esac
    [ -f "${directory}/${key}" ] || die "snapshot lacks media referenced by ${db}"
  done < "${references}"
}

# Every service that writes to PostgreSQL, Redis or MinIO. Only those defined in the
# Compose project are touched, so older deployments without a worker still work.
WRITER_SERVICES="api worker-asr worker-emotion worker-llm worker-assistant worker-notify worker-meeting worker-dispatch worker-provision worker-organization-data worker-tenant-backup"

defined_writers() {
  local defined svc
  defined="$(docker compose config --services)"
  for svc in ${WRITER_SERVICES}; do
    if printf '%s\n' "${defined}" | grep -qx "${svc}"; then
      printf '%s ' "${svc}"
    fi
  done
}

stop_writers() {
  local writers
  writers="$(defined_writers)"
  log "stopping writers: ${writers}"
  [ -n "${writers}" ] || return 0
  # shellcheck disable=SC2086
  docker compose stop ${writers}
}

start_writers() {
  local writers
  writers="$(defined_writers)"
  log "starting writers: ${writers}"
  [ -n "${writers}" ] || return 0
  # shellcheck disable=SC2086
  docker compose up -d ${writers}
}

tenant_db_name() {
  local raw="${1//-/}"
  raw="${raw#cbi_tenant_}"
  raw="${raw%_app}"
  printf '%s' "${raw}" | grep -Eq '^[0-9a-fA-F]{32}$' \
    || die "not a tenant UUID or cbi_tenant_<hex> name: $1"
  printf 'cbi_tenant_%s' "$(printf '%s' "${raw}" | tr 'A-F' 'a-f')"
}

# Mirrors the grants tenant_provisioning.py applies after a tenant database is created.
tenant_grants_sql() {
  local db="$1" role="${1}_app"
  cat <<SQL
GRANT CONNECT, TEMPORARY ON DATABASE ${db} TO ${role};
GRANT USAGE ON SCHEMA public TO ${role};
GRANT USAGE ON SCHEMA ag_catalog TO ${role};
GRANT SELECT ON ag_catalog.ag_graph TO ${role};
GRANT USAGE, CREATE ON SCHEMA tenant_graph TO ${role};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ${role};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ${role};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA tenant_graph TO ${role};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tenant_graph TO ${role};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${role};
GRANT SELECT ON tenant_identity TO ${role};
SQL
}

# Re-link Apache AGE graphs after pg_restore: pg_dump keeps the source graph ids, AGE expects the
# graph schema oid, so every Cypher query fails until they match. Keep identical to
# AGE_GRAPH_REPAIR_SQL in apps/api/app/services/apache_age.py (a test checks this).
repair_age_graphs() {
  local db="$1"
  docker compose exec -T postgres psql -U cbi -d "${db}" -v ON_ERROR_STOP=1 -q <<'AGE_SQL'
DO $age_repair$
BEGIN
  IF EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE graphid <> namespace::oid) THEN
    ALTER TABLE ag_catalog.ag_label DROP CONSTRAINT fk_graph_oid;
    UPDATE ag_catalog.ag_label AS l SET graph = g.namespace::oid
      FROM ag_catalog.ag_graph AS g WHERE l.graph = g.graphid AND g.graphid <> g.namespace::oid;
    UPDATE ag_catalog.ag_graph SET graphid = namespace::oid WHERE graphid <> namespace::oid;
    ALTER TABLE ag_catalog.ag_label ADD CONSTRAINT fk_graph_oid
      FOREIGN KEY (graph) REFERENCES ag_catalog.ag_graph(graphid);
  END IF;
END
$age_repair$
AGE_SQL
}

# Restore one database dump into a brand new database and swap it in by renaming.
# The previous database is kept as <name>_pre<stamp> so a bad restore is reversible.
#   swap_restore_database <db> <dump-file> <stamp>
swap_restore_database() {
  local db="$1" dump="$2" stamp="$3" fresh old
  fresh="${db}_new${stamp}"
  old="${db}_pre${stamp}"
  [ "${#old}" -le 63 ] || die "generated database name too long: ${old}"

  log "restoring ${db} into fresh database ${fresh}"
  psql_admin -c "DROP DATABASE IF EXISTS ${fresh}" -c "CREATE DATABASE ${fresh} ENCODING 'UTF8' TEMPLATE template0"
  if ! docker compose exec -T postgres pg_restore -U cbi -d "${fresh}" \
      --no-owner --no-acl --exit-on-error --single-transaction < "${dump}"; then
    psql_admin -c "DROP DATABASE IF EXISTS ${fresh}" || true
    die "pg_restore failed for ${db}; the live database was not touched"
  fi
  if ! repair_age_graphs "${fresh}"; then
    psql_admin -c "DROP DATABASE IF EXISTS ${fresh}" || true
    die "Apache AGE graph repair failed for ${db}; the live database was not touched"
  fi

  log "swapping ${db} (old copy kept as ${old})"
  psql_admin -c "ALTER DATABASE ${db} ALLOW_CONNECTIONS false" \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${db}' AND pid <> pg_backend_pid()" >/dev/null
  psql_admin -c "ALTER DATABASE ${db} RENAME TO ${old}" -c "ALTER DATABASE ${fresh} RENAME TO ${db}"
  psql_admin -c "ALTER DATABASE ${old} ALLOW_CONNECTIONS true" >/dev/null
}
