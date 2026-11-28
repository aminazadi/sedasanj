#!/bin/sh
# Lints every PHP file of freepbx-module/ and runs freepbx-module/tests/*.php on each PHP version
# in a container (PHP is not installed on the maintainer's Mac). Usage: scripts/test-freepbx-module.sh [version ...]
# Default versions: 7.4 8.1 8.3 (FreePBX 16 runs 7.4, FreePBX 17 runs 8.2; 8.1/8.3 catch drift).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSIONS="${*:-7.4 8.1 8.3}"
status=0
# Test a snapshot: bind-mounting the live tree races with editors on macOS (files read as empty or
# unreadable right after a write), which shows up as spurious lint failures.
#
# The snapshot must live where the container runtime can actually mount it. Docker Desktop, colima
# and lima share $HOME (and often $TMPDIR); a checkout on another volume (e.g. /Volumes/...) or a
# TMPDIR outside the share mounts as an empty directory, so the tests would "find no files".
MOUNT_ROOT=${SEDA_SANJ_MOUNT_ROOT:-$HOME}
[ -d "$MOUNT_ROOT" ] || { echo "ERROR: MOUNT_ROOT $MOUNT_ROOT is not a directory" >&2; exit 1; }
SNAPSHOT=$(mktemp -d "${MOUNT_ROOT%/}/.sedasanj-test.XXXXXXXX") || {
  echo "ERROR: cannot create a test snapshot under $MOUNT_ROOT; set SEDA_SANJ_MOUNT_ROOT to a directory shared with the container runtime" >&2
  exit 1
}
trap 'rm -rf "$SNAPSHOT"' EXIT HUP INT TERM
cp -RL "$ROOT/freepbx-module" "$SNAPSHOT/m"
# Fail loudly if the snapshot is not a real module tree; an empty or unmountable snapshot used to
# surface only as "Could not open input file: /m/tests/*Test.php" from inside the container.
[ -d "$SNAPSHOT/m/tests" ] && [ -d "$SNAPSHOT/m/engine" ] || {
  echo "ERROR: snapshot $SNAPSHOT/m is incomplete" >&2
  exit 1
}
for v in $VERSIONS; do
  echo "=== PHP $v"
  docker run --rm -v "$SNAPSHOT/m":/m:ro "php:$v-cli" sh -c '
    rc=0
    php -v | head -1
    for f in $(find /m -name "*.php" -not -path "*/tests/fixtures/*"); do
      php -l "$f" >/dev/null || { echo "LINT FAIL $f"; rc=1; }
    done
    for t in /m/tests/*Test.php; do
      out=$(php "$t" 2>&1) || { echo "TEST FAIL $t"; echo "$out" | tail -15; rc=1; continue; }
      echo "ok  $(basename "$t")"
    done
    exit $rc' || status=1
done
exit $status
