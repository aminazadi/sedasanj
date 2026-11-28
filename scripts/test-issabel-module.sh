#!/bin/bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd)
# The snapshot must live where the container runtime can actually mount it. Docker Desktop, colima
# and lima share $HOME (and often $TMPDIR); a checkout on another volume (e.g. /Volumes/...) or a
# TMPDIR outside the share mounts as an empty directory, so the tests would "find no files".
MOUNT_ROOT=${SEDA_SANJ_MOUNT_ROOT:-$HOME}
[ -d "$MOUNT_ROOT" ] || { echo "ERROR: MOUNT_ROOT $MOUNT_ROOT is not a directory" >&2; exit 1; }
WORK=$(mktemp -d "${MOUNT_ROOT%/}/.sedasanj-test.XXXXXXXX") || {
  echo "ERROR: cannot create a test snapshot under $MOUNT_ROOT; set SEDA_SANJ_MOUNT_ROOT to a directory shared with the container runtime" >&2
  exit 1
}
trap 'rm -rf "$WORK"' EXIT
python3 - "$ROOT/issabel-module" "$WORK/module" <<'PYTHON'
import shutil,sys
shutil.copytree(sys.argv[1], sys.argv[2], symlinks=False, ignore=shutil.ignore_patterns('7zzs-*', 'ffmpeg-*', 'gsm-encode-x86_64', 'gsm-encode-aarch64'))
PYTHON
# Fail loudly if the snapshot is not a real module tree; an empty or unmountable snapshot used to
# surface only as "Could not open input file: /m/tests/..." from inside the container.
[ -d "$WORK/module/tests" ] || { echo "ERROR: snapshot $WORK/module is incomplete" >&2; exit 1; }
for VERSION in "${@:-5.6 7.4 8.2}"; do
  for PHP_VERSION in $VERSION; do
    docker run --rm -v "$WORK/module:/m:ro" "php:$PHP_VERSION-cli" sh -c '
      set -e
      find /m -name "*.php" -not -path "/m/engine/*" -not -path "/m/bin/*" -not -path "/m/tests/*" -print0 | xargs -0 -n1 php -l
      php /m/tests/DialplanTest.php
      php /m/tests/WebSecurityTest.php
      php /m/tests/NativeAclTest.php
      if php -r "exit(PHP_VERSION_ID >= 70400 ? 0 : 1);"; then
        find /m/engine /m/bin -name "*.php" -print0 | xargs -0 -n1 php -l
        php /m/tests/SettingsTest.php
        php /m/tests/TarArchiveTest.php
      fi'
  done
done
