#!/bin/bash
#
# activate.sh - finish a Module Admin (web GUI) installation. Run as root:
#
#   sudo bash /var/www/html/admin/modules/recuploader/activate.sh
#
# Module Admin installs the module as the web user, which cannot create the systemd unit, the sudoers
# drop-in or the update helper, or patch FreePBX. This script performs exactly that root-only part by
# calling the module's own provision() through the FreePBX bootstrap, so a GUI install and an
# install.sh run end in the same state. It is safe to run again (upgrades, repairs).
#
# Exit codes: 0 provisioned, 1 not root / prerequisites, 2 provisioning failed (details printed and
# in /var/log/asterisk-recording-uploader/uploader.log).

set -uo pipefail

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "ERROR [SS-SYS-1004]: activation must run as root. Use: sudo bash $0" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHP_BIN="$(command -v php || true)"
if [ -z "$PHP_BIN" ]; then
  echo "ERROR [SS-SYS-1001]: no php CLI found on PATH. Install php-cli (PHP 7.4 or newer)." >&2
  exit 1
fi
if ! "$PHP_BIN" -r 'exit(PHP_VERSION_ID >= 70400 ? 0 : 1);'; then
  echo "ERROR [SS-SYS-1001]: the CLI PHP ($("$PHP_BIN" -r 'echo PHP_VERSION;')) is older than 7.4." >&2
  exit 1
fi
if [ ! -f /etc/freepbx.conf ]; then
  echo "ERROR [SS-SYS-1003]: /etc/freepbx.conf not found - this does not look like a FreePBX host." >&2
  exit 1
fi
if [ ! -f "$HERE/Recuploader.class.php" ]; then
  echo "ERROR: run this script from the installed module directory (Recuploader.class.php not found next to it)." >&2
  exit 1
fi

echo "==> Provisioning Seda Sanj (backup, engine, service, helper, hooks)"
"$PHP_BIN" -d display_errors=stderr -r '
  $_SERVER["HTTP_HOST"] = "localhost";
  require "/etc/freepbx.conf";
  try {
      \FreePBX::Create()->Recuploader->provision();
  } catch (\Throwable $e) {
      fwrite(STDERR, "ERROR: " . $e->getMessage() . "\n");
      exit(2);
  }
  echo "provisioned\n";
'
status=$?
if [ $status -ne 0 ]; then
  echo "Activation failed (exit $status). Fix the cause above and run this command again." >&2
  exit 2
fi

if command -v fwconsole >/dev/null 2>&1; then
  fwconsole chown >/dev/null 2>&1 || true
fi
echo "==> Done. Open Admin > Seda Sanj: the activation notice should be gone and the service running."
