#!/bin/bash
set -euo pipefail
[ "$EUID" -eq 0 ] || { echo 'SS-SYS-1004: Run uninstall as root.' >&2; exit 1; }
# Keep queue, recordings, configuration and verified backups by default.
PHP_BIN=$(cat /etc/sedasanj-recuploader-update/php-path)
exec "$PHP_BIN" /usr/local/lib/sedasanj-issabel/bin/provision.php --uninstall
