#!/usr/bin/env bash
# Start everything needed for a local laptop test:
#   Postgres + Redis + MinIO (Docker), API, durable-dispatch/ASR/LLM/notify
#   workers, and both Vite panels.
#
# Usage (from anywhere):
#   ./scripts/dev.sh
#
# Ctrl-C stops the app processes. Docker infra stays up so the next run is faster.
#   ./scripts/dev.sh --down     # stop Postgres/Redis/MinIO only

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f deploy/compose.local.yml)
PIDS=()

log() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

port_open() {
  local host="$1" port="$2"
  (echo >/dev/tcp/"${host}"/"${port}") >/dev/null 2>&1
}

wait_port() {
  local host="$1" port="$2" name="$3"
  local i
  for i in $(seq 1 60); do
    if port_open "${host}" "${port}"; then
      log "  ${name} → ${host}:${port}"
      return 0
    fi
    sleep 1
  done
  die "timed out waiting for ${name} on ${host}:${port}"
}

ensure_docker() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  if command -v colima >/dev/null 2>&1; then
    log "Docker is down; starting Colima…"
    colima start
  fi
  docker info >/dev/null 2>&1 || die "Docker is not running (start Colima or Docker Desktop)"
}

ensure_infra() {
  if port_open 127.0.0.1 5433 && port_open 127.0.0.1 6380 && port_open 127.0.0.1 9000; then
    log "Postgres / Redis / MinIO already listening."
  else
    log "Starting local Docker infra (deploy/compose.local.yml)…"
    "${COMPOSE[@]}" up -d
    wait_port 127.0.0.1 5433 Postgres
    wait_port 127.0.0.1 6380 Redis
    wait_port 127.0.0.1 9000 MinIO
  fi
  ensure_app_db_role
}

ensure_app_db_role() {
  # Migrations GRANT to cbi_app; volumes started without deploy/postgres/init lack it.
  local cid
  cid="$(docker ps --filter publish=5433 --format '{{.ID}}' | head -1 || true)"
  [[ -n "${cid}" ]] || return 0
  docker exec "${cid}" psql -U root -d cbi -v ON_ERROR_STOP=1 -c \
    "DO \$\$ BEGIN
       IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cbi_app') THEN
         CREATE ROLE cbi_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
           PASSWORD 'cbi_app';
       END IF;
     END \$\$;
     GRANT CONNECT ON DATABASE cbi TO cbi_app;
     GRANT USAGE ON SCHEMA public TO cbi_app;" >/dev/null
}

run() {
  local name="$1"
  shift
  "$@" > >(
    while IFS= read -r line; do
      printf '[%s] %s\n' "${name}" "${line}"
    done
  ) 2>&1 &
  PIDS+=("$!")
}

if [[ "${1:-}" == "--down" ]]; then
  ensure_docker
  "${COMPOSE[@]}" down
  log "Local Docker infra stopped."
  exit 0
fi

cleanup() {
  trap - EXIT INT TERM
  log "Stopping app processes…"
  if ((${#PIDS[@]})); then
    kill "${PIDS[@]}" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

[[ -f "${ROOT}/.env" ]] || die "missing .env; run: cp .env.example .env"
command -v uv >/dev/null 2>&1 || die "uv is not on PATH"
command -v ffmpeg >/dev/null 2>&1 || log "warning: ffmpeg not found (ASR channel split needs it)"

# Export .env into this shell so alembic / workers see DATABASE_URL etc.
# Alembic reads os.environ only (it does not load the .env file itself).
set -a
# shellcheck disable=SC1091
source "${ROOT}/.env"
set +a
[[ -n "${DATABASE_URL:-}" ]] || die "DATABASE_URL is missing from .env"

ensure_docker
ensure_infra

if [[ ! -d "${ROOT}/.venv" ]]; then
  log "Creating Python venv…"
  uv venv --python 3.12
  uv pip install -e ".[dev]"
fi

log "Applying migrations…"
uv run alembic -c apps/api/alembic.ini upgrade head

if [[ ! -d "${ROOT}/web/client/node_modules" ]]; then
  log "Installing client panel packages…"
  (cd web/client && npm install)
fi
if [[ ! -d "${ROOT}/web/admin/node_modules" ]]; then
  log "Installing admin panel packages…"
  (cd web/admin && npm install)
fi

export PYTHONUNBUFFERED=1

log "Starting API, workers, and panels…"
run api uv run uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000
run asr env WORKER_METRICS_PORT=9101 uv run arq worker_asr.main.WorkerSettings
run llm env WORKER_METRICS_PORT=9102 uv run arq worker_llm.main.WorkerSettings
run notify env WORKER_METRICS_PORT=9103 uv run arq worker_notify.main.WorkerSettings
run dispatch env WORKER_METRICS_PORT=9104 uv run arq worker_dispatch.main.WorkerSettings
run client npm --prefix web/client run dev
run admin npm --prefix web/admin run dev

wait_port 127.0.0.1 8000 API
wait_port 127.0.0.1 5173 "client panel"
wait_port 127.0.0.1 5174 "admin panel"

cat <<'EOF'

Local stack is up. Ctrl-C stops the apps; Docker stays running.

  API     http://127.0.0.1:8000/docs
  Client  http://127.0.0.1:5173
  Admin   http://127.0.0.1:5174
  MinIO   http://127.0.0.1:9001

EOF

wait
