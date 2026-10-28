#!/bin/bash

set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "ERROR: backup restore must run as root." >&2
  exit 1
fi

BACKUP_DIR="${1:-}"
if [ -z "$BACKUP_DIR" ] || [ ! -d "$BACKUP_DIR" ]; then
  echo "Usage: sudo ./restore-installation-backup.sh /var/backups/sedasanj-recuploader/<backup>" >&2
  exit 2
fi
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd -P)"

for required_file in filesystem.tar.gz manifest.txt present-paths.txt absent-paths.txt SHA256SUMS; do
  if [ ! -f "$BACKUP_DIR/$required_file" ]; then
    echo "ERROR: incomplete backup: missing $required_file" >&2
    exit 1
  fi
done

if ! grep -qx 'schema=sedasanj.recuploader.install-backup' "$BACKUP_DIR/manifest.txt"; then
  echo "ERROR: unsupported backup manifest." >&2
  exit 1
fi
if ! grep -qx 'version=1' "$BACKUP_DIR/manifest.txt"; then
  echo "ERROR: unsupported backup version." >&2
  exit 1
fi

(
  cd "$BACKUP_DIR"
  sha256sum -c SHA256SUMS
)

is_managed_path() {
  case "$1" in
    var/www/html/admin/modules/recuploader|\
    var/www/html/admin/modules/callrecording/functions.inc.php|\
    etc/asterisk/globals_custom.conf|\
    etc/asterisk/extensions_custom.conf|\
    etc/systemd/system/asterisk-recording-uploader.service|\
    etc/sudoers.d/asterisk-recording-uploader|\
    usr/local/bin/asterisk-recording-uploader|\
    etc/asterisk-recording-uploader|\
    var/lib/asterisk-recording-uploader|\
    var/spool/asterisk-recording-uploader|\
    var/log/asterisk-recording-uploader) return 0 ;;
    *) return 1 ;;
  esac
}

while IFS= read -r relative_path; do
  if ! is_managed_path "$relative_path"; then
    echo "ERROR: backup contains an unsafe path: $relative_path" >&2
    exit 1
  fi
done < "$BACKUP_DIR/present-paths.txt"
while IFS= read -r relative_path; do
  if ! is_managed_path "$relative_path"; then
    echo "ERROR: backup contains an unsafe path: $relative_path" >&2
    exit 1
  fi
done < "$BACKUP_DIR/absent-paths.txt"

systemctl stop asterisk-recording-uploader.service 2>/dev/null || true

while IFS= read -r relative_path; do
  rm -rf -- "/${relative_path}"
done < "$BACKUP_DIR/absent-paths.txt"

tar -C / -xzpf "$BACKUP_DIR/filesystem.tar.gz"
systemctl daemon-reload
fwconsole reload

if grep -qx 'service_was_active=yes' "$BACKUP_DIR/manifest.txt"; then
  systemctl enable asterisk-recording-uploader.service 2>/dev/null || true
  systemctl restart asterisk-recording-uploader.service
else
  systemctl stop asterisk-recording-uploader.service 2>/dev/null || true
fi

echo "Backup restored from $BACKUP_DIR"
