#!/bin/bash
set -euo pipefail
[ "$EUID" -eq 0 ] || { echo 'SS-SYS-1004: Run activation as root.' >&2; exit 1; }
SOURCE=$(cd -- "$(dirname -- "$0")" && pwd)
PHP_BIN=${1:-/usr/bin/php}
SYSTEM_PHP=/usr/bin/php
[ -x "$PHP_BIN" ] && [ -x "$SYSTEM_PHP" ] || { echo 'SS-SYS-1011: Specify an installed PHP CLI 7.4+ executable.' >&2; exit 1; }
PHP_BIN=$(readlink -f -- "$PHP_BIN")
CHECK=$PHP_BIN
while [ "$CHECK" != / ]; do
  [ "$(stat -c %u -- "$CHECK")" = 0 ] || { echo 'SS-SYS-1011: PHP and its parents must be root-owned.' >&2; exit 1; }
  MODE=$(stat -c %a -- "$CHECK")
  (( (8#$MODE & 8#22) == 0 )) || { echo 'SS-SYS-1011: PHP and its parents must not be group/world writable.' >&2; exit 1; }
  CHECK=$(dirname -- "$CHECK")
done
"$PHP_BIN" -r 'exit(PHP_VERSION_ID >= 70400 ? 0 : 1);' || { echo 'SS-SYS-1011: Select a separate PHP CLI 7.4 or newer.' >&2; exit 1; }
# Credentials travel only through a pipe and are never included in process arguments.
"$SYSTEM_PHP" "$SOURCE/lib/bridge.php" inventory | "$PHP_BIN" "$SOURCE/bin/provision.php" "$SOURCE" "$PHP_BIN"
