#!/usr/bin/env bash
# Production deploy that builds each image once.
#
# Every image is tagged with a hash of exactly the files that go into it. An image whose tag
# already exists is reused, so an unchanged deploy builds nothing; changed sources get a new
# tag and are rebuilt, so stale code is never started.
#
#   scripts/deploy.sh                 build only what is missing, then start everything
#   scripts/deploy.sh --build-only    build what is missing, do not start
#   scripts/deploy.sh --rebuild       ignore existing images and rebuild all of them
#   scripts/deploy.sh up -d api       any other arguments go to `docker compose up`
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/deploy"

if command -v sha256sum >/dev/null 2>&1; then SUM=(sha256sum); else SUM=(shasum -a 256); fi

# hash_of <path>...: stable content hash of files and directories (names + bytes).
hash_of() {
  (
    cd "$ROOT"
    for path in "$@"; do
      if [ -d "$path" ]; then
        find "$path" -type f \
          ! -path '*/node_modules/*' ! -path '*/dist/*' ! -path '*/__pycache__/*' \
          ! -name '.DS_Store' ! -name '*.pyc' ! -path 'scripts/deploy.sh'
      elif [ -f "$path" ]; then
        printf '%s\n' "$path"
      fi
    done | LC_ALL=C sort | while IFS= read -r file; do
      printf '%s\n' "$file"
      "${SUM[@]}" <"$file"
    done | "${SUM[@]}" | cut -c1-16
  )
}

env_value() { # env_value NAME DEFAULT: value from the shell or deploy/.env
  local value="${!1:-}"
  if [ -z "$value" ] && [ -f .env ]; then
    value="$(grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true)"
  fi
  printf '%s' "${value:-$2}"
}

SITE_URL_VALUE="$(env_value SITE_URL "https://$(env_value APP_DOMAIN none)")"
AGE_COMMIT_VALUE="$(env_value AGE_COMMIT 2db2f060c4c9265a14d40f007eb8c56febf31e4c)"

export API_TAG="$(hash_of pyproject.toml README.md apps scripts deploy/Dockerfile.api)"
export POSTGRES_TAG="$(hash_of deploy/Dockerfile.postgres deploy/postgres/healthcheck.sh)-$(printf '%s' "$AGE_COMMIT_VALUE" | "${SUM[@]}" | cut -c1-8)"
export CLIENT_TAG="$(hash_of web/shared web/client deploy/web-server.mjs deploy/Dockerfile.web)-$(printf '%s' "$SITE_URL_VALUE" | "${SUM[@]}" | cut -c1-8)"
export ADMIN_TAG="$(hash_of web/shared web/admin deploy/web-server.mjs deploy/Dockerfile.web)"

REBUILD=0
BUILD_ONLY=0
case "${1:-}" in
  --rebuild) REBUILD=1; shift ;;
  --build-only) BUILD_ONLY=1; shift ;;
esac

# image -> one compose service that builds it
declare -a TARGETS=(
  "sedasanj/api-base:$API_TAG migrate"
  "sedasanj/api:$API_TAG api"
  "sedasanj/emotion:$API_TAG worker-emotion"
  "sedasanj/postgres:$POSTGRES_TAG postgres"
  "sedasanj/client:$CLIENT_TAG client"
  "sedasanj/admin:$ADMIN_TAG admin"
)

to_build=()
for entry in "${TARGETS[@]}"; do
  image="${entry%% *}"
  service="${entry##* }"
  if [ "$REBUILD" = 1 ] || ! docker image inspect "$image" >/dev/null 2>&1; then
    to_build+=("$service")
    echo "build: $image (missing)"
  else
    echo "reuse: $image"
  fi
done

if [ "${#to_build[@]}" -gt 0 ]; then
  docker compose build "${to_build[@]}"
fi

[ "$BUILD_ONLY" = 1 ] && exit 0

if [ "$#" -gt 0 ]; then
  exec docker compose "$@" --no-build
fi
exec docker compose up -d --no-build --remove-orphans
