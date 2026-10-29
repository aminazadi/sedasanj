#!/bin/sh
# Lints every PHP file of freepbx-module/ and runs freepbx-module/tests/*.php on each PHP version
# in a container (PHP is not installed on the maintainer's Mac). Usage: scripts/test-freepbx-module.sh [version ...]
# Default versions: 7.4 8.1 8.3 (FreePBX 16 runs 7.4, FreePBX 17 runs 8.2; 8.1/8.3 catch drift).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSIONS="${*:-7.4 8.1 8.3}"
status=0
for v in $VERSIONS; do
  echo "=== PHP $v"
  docker run --rm -v "$ROOT/freepbx-module":/m:ro "php:$v-cli" sh -c '
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
