#!/bin/bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
python3 - "$ROOT/issabel-module" "$WORK/module" <<'PYTHON'
import shutil,sys
shutil.copytree(sys.argv[1], sys.argv[2], symlinks=False, ignore=shutil.ignore_patterns('7zzs-*', 'ffmpeg-*', 'gsm-encode-x86_64', 'gsm-encode-aarch64'))
PYTHON
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
