#!/bin/bash
#
# uninstall.sh - fully uninstall the Seda Sanj (recuploader) module: unregister
# it from FreePBX AND remove everything install.sh provisioned at the OS level.
#
# Safe to run on its own - you do NOT need to go through the FreePBX GUI (Module
# Admin) first. If the module's own PHP uninstall() already ran (GUI path), the
# `fwconsole ma uninstall` call below simply no-ops/fails harmlessly and the
# OS-level cleanup that follows still runs, which is also what catches anything
# uninstall() couldn't remove without root (systemd unit, sudoers file,
# dialplan/globals blocks).
#
# Usage:
#   sudo ./uninstall.sh            # remove the module, keep config/state/spool/logs
#   sudo ./uninstall.sh --purge    # also remove config, state, spool (pending,
#                                  # failed and uploaded folders - including any
#                                  # recordings still waiting or parked there)
#                                  # and logs
#
# Nothing installed via apt (php-cli, php-curl, php-sqlite3) is removed -
# those are shared system packages this module must not assume it can rip out.

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./uninstall.sh)" >&2
  exit 1
fi

# Removes the block between two marker lines. If the BEGIN marker has no END marker after it, the file
# is left untouched: a sed range delete would otherwise run to the end of the file and truncate it.
remove_block() {
  local file="$1" begin="$2" end="$3" b e
  [ -f "$file" ] || return 0
  b="$(grep -nF -- "$begin" "$file" | head -n 1 | cut -d: -f1 || true)"
  [ -n "$b" ] || return 0
  e="$(awk -v s="$b" -v m="$end" 'NR > s && index($0, m) { print NR; exit }' "$file")"
  if [ -z "$e" ]; then
    echo "WARNING: $file has a BEGIN marker without a matching END marker; leaving it untouched." >&2
    return 1
  fi
  sed -i "${b},${e}d" "$file"
}

PURGE=false
if [ "${1:-}" = "--purge" ]; then
  PURGE=true
fi

MODULE_DIR=/var/www/html/admin/modules/recuploader
CALLRECORDING_FILE=/var/www/html/admin/modules/callrecording/functions.inc.php
if [ -f "$MODULE_DIR/patch-callrecording.php" ] && command -v php >/dev/null 2>&1; then
  # A failed restore (core file changed since we patched it) must not abort the uninstall half-way.
  php "$MODULE_DIR/patch-callrecording.php" restore "$CALLRECORDING_FILE" 0 \
    /var/lib/asterisk-recording-uploader \
    || echo "WARNING: could not restore $CALLRECORDING_FILE (it changed since the patch). Reinstall the callrecording module with: fwconsole ma downloadinstall callrecording" >&2
fi

# Best-effort: unregister the module from FreePBX first, mirroring what
# Recuploader::uninstall() does when FreePBX runs `fwconsole ma uninstall`.
echo "==> Unregistering module from FreePBX (best-effort)"
fwconsole ma uninstall recuploader || true

echo "==> Stopping and removing the service"
systemctl disable --now asterisk-recording-uploader.service 2>/dev/null || true
rm -f /etc/systemd/system/asterisk-recording-uploader.service
systemctl daemon-reload

rm -f /etc/sudoers.d/asterisk-recording-uploader
rm -f /usr/local/sbin/sedasanj-recuploader-update
rm -rf /etc/sedasanj-recuploader-update

if [ -f "$CALLRECORDING_FILE" ] && [ -f "${CALLRECORDING_FILE}.orig" ] && command -v php >/dev/null 2>&1; then
  if php -r '
    $current = file_get_contents($argv[1]);
    $original = file_get_contents($argv[2]);
    $restored = str_replace(
      [
        "\x27a\${EVAL(\${MONITOR_REC_OPTION})}i(\${LOCAL_MIXMON_ID})\${MIXMON_BEEP}\x27,\x27\${EVAL(\${MIXMON_POST})}\x27",
        "\x27a\${EVAL(\${MONITOR_REC_OPTION})}i(LOCAL_MIXMON_ID)\${MIXMON_BEEP}\x27,\x27\${EVAL(\${MIXMON_POST})}\x27",
      ],
      [
        "\x27a\${MONITOR_REC_OPTION}i(\${LOCAL_MIXMON_ID})\${MIXMON_BEEP}\x27,\x27\${MIXMON_POST}\x27",
        "\x27ai(LOCAL_MIXMON_ID)\${MIXMON_BEEP}\x27,\x27\${EVAL(\${MIXMON_POST})}\x27",
      ],
      $current
    );
    exit(hash_equals(hash("sha256", $original), hash("sha256", $restored)) ? 0 : 1);
  ' "$CALLRECORDING_FILE" "${CALLRECORDING_FILE}.orig"; then
    cp "${CALLRECORDING_FILE}.orig" "$CALLRECORDING_FILE"
    rm -f "${CALLRECORDING_FILE}.orig"
    echo "Restored the verified pre-module callrecording core backup."
  else
    echo "WARNING: callrecording core changed after the old patch; backup was not restored." >&2
  fi
fi

MARKER_BEGIN="; BEGIN recuploader dialplan hook - managed by the Recording Uploader module, do not edit by hand"
MARKER_END="; END recuploader dialplan hook"
# This dialplan-hook path (scorer.py) was retired well before the PHP
# rewrite, but a box that was installed before then may still have this
# block - clean it up here too so uninstall is thorough regardless of
# which version was running.
remove_block /etc/asterisk/extensions_custom.conf "$MARKER_BEGIN" "$MARKER_END" || true

MIXMON_MARKER_BEGIN="; BEGIN recuploader mixmon globals - managed by the Recording Uploader module, do not edit by hand"
MIXMON_MARKER_END="; END recuploader mixmon globals"
remove_block /etc/asterisk/globals_custom.conf "$MIXMON_MARKER_BEGIN" "$MIXMON_MARKER_END" || true
fwconsole reload || asterisk -rx "dialplan reload" || true

rm -rf /usr/local/bin/asterisk-recording-uploader
# Leftovers from pre-rewrite (Python-based) versions, cleaned up here so
# uninstall is thorough regardless of which version was running:
#   - the dedicated Python venv some older builds used
#   - the bash wrapper script that used to be the MIXMON_POST entry point
#     (bin/mix-stereo.php is called directly now - see
#     Recuploader::injectMixmonGlobals())
#   - a leftover temporary staging copy from older install.sh versions that
#     didn't clean up after themselves
rm -rf /usr/local/lib/asterisk-recording-uploader
rm -f /usr/bin/mix-stereo.sh
rm -rf /usr/src/recuploader

if [ "$PURGE" = true ]; then
  # SPOOL_DIR includes the pending/failed/uploaded subdirectories, so any
  # recordings still waiting in pending/ or parked in failed/ go with it.
  rm -rf /etc/asterisk-recording-uploader /var/lib/asterisk-recording-uploader \
         /var/spool/asterisk-recording-uploader /var/log/asterisk-recording-uploader \
         /var/lib/sedasanj-recuploader-update
  echo "Purged config/state/spool/logs."
else
  echo "Left config/state/spool/logs in place. Re-run with --purge to remove those too."
fi
