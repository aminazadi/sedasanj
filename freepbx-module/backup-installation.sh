#!/bin/bash

set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "ERROR: installation backup must run as root." >&2
  exit 1
fi

umask 077

BACKUP_ROOT="${SEDA_SANJ_BACKUP_ROOT:-/var/backups/sedasanj-recuploader}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}-$$"
ARCHIVE="${BACKUP_DIR}/filesystem.tar.gz"
PRESENT_LIST="${BACKUP_DIR}/present-paths.txt"
ABSENT_LIST="${BACKUP_DIR}/absent-paths.txt"
MANIFEST="${BACKUP_DIR}/manifest.txt"

MANAGED_PATHS=(
  "var/www/html/admin/modules/recuploader"
  "var/www/html/admin/modules/callrecording/functions.inc.php"
  "etc/asterisk/globals_custom.conf"
  "etc/asterisk/extensions_custom.conf"
  "etc/systemd/system/asterisk-recording-uploader.service"
  "etc/sudoers.d/asterisk-recording-uploader"
  "usr/local/bin/asterisk-recording-uploader"
  "etc/asterisk-recording-uploader"
  "var/lib/asterisk-recording-uploader"
  "var/spool/asterisk-recording-uploader"
  "var/log/asterisk-recording-uploader"
)

mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"
mkdir "$BACKUP_DIR"

cleanup_failed_backup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    rm -rf -- "$BACKUP_DIR"
    echo "ERROR: installation backup failed; installation was not started." >&2
  fi
  exit "$status"
}
trap cleanup_failed_backup EXIT

: > "$PRESENT_LIST"
: > "$ABSENT_LIST"
for relative_path in "${MANAGED_PATHS[@]}"; do
  if [ -e "/${relative_path}" ] || [ -L "/${relative_path}" ]; then
    printf '%s\n' "$relative_path" >> "$PRESENT_LIST"
  else
    printf '%s\n' "$relative_path" >> "$ABSENT_LIST"
  fi
done

required_kb=102400
while IFS= read -r relative_path; do
  path_kb="$(du -sk -- "/${relative_path}" 2>/dev/null | awk '{print $1}')"
  required_kb=$((required_kb + ${path_kb:-0}))
done < "$PRESENT_LIST"
available_kb="$(df -Pk "$BACKUP_ROOT" | awk 'NR == 2 {print $4}')"
if [ -z "$available_kb" ] || [ "$available_kb" -lt "$required_kb" ]; then
  echo "ERROR: insufficient free space for a safe installation backup." >&2
  echo "Required (conservative): ${required_kb} KiB; available: ${available_kb:-unknown} KiB." >&2
  exit 1
fi

service_active=no
if systemctl is-active --quiet asterisk-recording-uploader.service 2>/dev/null; then
  service_active=yes
fi

freepbx_version="$(fwconsole --version 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g' || true)"
php_version="$(php -r 'echo PHP_VERSION;' 2>/dev/null || true)"

{
  printf 'schema=sedasanj.recuploader.install-backup\n'
  printf 'version=1\n'
  printf 'created_at=%s\n' "$TIMESTAMP"
  printf 'hostname=%s\n' "$(hostname 2>/dev/null || printf unknown)"
  printf 'freepbx_version=%s\n' "${freepbx_version:-unknown}"
  printf 'php_version=%s\n' "${php_version:-unknown}"
  printf 'service_was_active=%s\n' "$service_active"
} > "$MANIFEST"

if [ -s "$PRESENT_LIST" ]; then
  tar -C / -czpf "${ARCHIVE}.tmp" -T "$PRESENT_LIST"
else
  tar -C / -czpf "${ARCHIVE}.tmp" --files-from /dev/null
fi
mv "${ARCHIVE}.tmp" "$ARCHIVE"

(
  cd "$BACKUP_DIR"
  sha256sum filesystem.tar.gz manifest.txt present-paths.txt absent-paths.txt > SHA256SUMS
)
chmod 600 "$BACKUP_DIR"/*

trap - EXIT
printf '%s\n' "$BACKUP_DIR"
