#!/bin/bash
#
# install.sh - install or upgrade the Seda Sanj (recuploader) FreePBX
# module on this box, end to end: module registration with FreePBX AND all
# OS-level provisioning (directories, PHP engine, apt dependencies,
# systemd unit, sudoers, MixMonitor globals, config).
#
# This is the FreePBX "frontend" install script (plan.md §3.4/§4 step 6).
# It bundles the host-agnostic engine/ tree (from this repo's top-level
# engine/ directory) into the deployed module and into
# /usr/local/bin/asterisk-recording-uploader - engine/ itself has no
# FreePBX dependency and knows nothing about this script.
#
# NOTE: this is this project's own manual, root-run script - it is not a
# FreePBX lifecycle hook, so it exists alongside (not instead of)
# Recuploader::install() (PHP), which attempts the same provisioning
# itself on `fwconsole ma install`. This script guarantees it actually
# happened regardless of whether that PHP step had root/permission.
#
# Based on the commands actually found to work on a live FreePBX server:
#   cp -r <source>/recuploader /usr/src/recuploader
#   chown -R asterisk:asterisk /usr/src/recuploader
#   chmod -R a+rX /usr/src/recuploader
#   cp -r /usr/src/recuploader /var/www/html/admin/modules/recuploader
#   chown -R asterisk:asterisk /var/www/html/admin/modules/recuploader
#   fwconsole ma install recuploader
#   fwconsole reload
#   (then the OS-level provisioning that used to live in postinstall.sh)
#
# `fwconsole ma installlocal` is attempted first (it's the documented path
# and works on a clean box), but since it did not work in practice here,
# this script does not depend on it succeeding - it falls through to the
# copy-then-`fwconsole ma install recuploader` sequence that is known to
# work, exactly as above.
#
# The temporary staging copy in /usr/src/recuploader (STAGING_DIR below) only
# exists while this script runs - it is removed again at the very end of a
# successful run, since nothing needs it once the module is installed.
#
# UPGRADE HANDLING: if the module is already installed, this script:
#   - fully replaces the deployed module directory and the bundled PHP
#     engine (BIN_DIR) rather than merging, so files removed/renamed in a
#     newer version don't linger from an old install
#   - explicitly re-injects the MixMonitor globals block, because FreePBX's
#     own Recuploader::injectMixmonGlobals() is a no-op once the BEGIN/END
#     marker already exists in globals_custom.conf - on a plain
#     `fwconsole ma install` of an already-installed module, an old
#     installation's globals would otherwise silently keep pointing at
#     whatever MIXMON_POST line an earlier version shipped
#   - one-way cleans up any leftover pre-1.0.0 dialplan-hook block (which
#     called the now-removed scorer.py) from extensions_custom.conf, and
#     never re-adds it - that path is retired, mixmon is the only
#     supported recording path now
#   - restarts the systemd service at the end (a plain enable/start does not
#     restart an already-running service, which is needed for it to pick up
#     new/changed engine code)
#   - leaves config.ini, the state file, the spool directories (including
#     any calls still waiting in the pending folder),
#     and logs untouched - those all live outside both the temporary
#     staging copy and the deployed module dir

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./install.sh)" >&2
  exit 1
fi

MODULE_RAWNAME=recuploader
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This script lives at <repo>/frontends/freepbx - the host-agnostic engine
# it bundles lives two levels up, at <repo>/engine.
REPO_ROOT="$(cd "$SOURCE_DIR/../.." && pwd)"
if [ -d "$SOURCE_DIR/engine" ]; then
  ENGINE_SRC="$SOURCE_DIR/engine"
else
  ENGINE_SRC="$REPO_ROOT/engine"
fi
# Temporary copy of the module source (frontend files + bundled engine),
# only needed while this script runs (fwconsole ma installlocal reads from
# it). Removed at the end.
STAGING_DIR=/usr/src/recuploader
MODULE_DIR=/var/www/html/admin/modules/recuploader
BIN_DIR=/usr/local/bin/asterisk-recording-uploader
CONF_DIR=/etc/asterisk-recording-uploader
STATE_DIR=/var/lib/asterisk-recording-uploader
SPOOL_DIR=/var/spool/asterisk-recording-uploader
LOG_DIR=/var/log/asterisk-recording-uploader
SERVICE_NAME=asterisk-recording-uploader.service

# Pre-1.0.0 dialplan-hook path (macro-hangupcall-custom -> scorer.py).
# Retired - these markers are only used to clean up a leftover block from
# an older install, never to re-inject it.
LEGACY_DIALPLAN_FILE=/etc/asterisk/extensions_custom.conf
LEGACY_MARKER_BEGIN="; BEGIN recuploader dialplan hook - managed by the Recording Uploader module, do not edit by hand"
LEGACY_MARKER_END="; END recuploader dialplan hook"

# The single supported recording path as of 1.0.0.
GLOBALS_FILE=/etc/asterisk/globals_custom.conf
MIXMON_MARKER_BEGIN="; BEGIN recuploader mixmon globals - managed by the Recording Uploader module, do not edit by hand"
MIXMON_MARKER_END="; END recuploader mixmon globals"

if [ ! -f "$SOURCE_DIR/module.xml" ]; then
  echo "Could not find module.xml next to install.sh (looked in $SOURCE_DIR)." >&2
  echo "Run this script from inside frontends/freepbx in the repo checkout." >&2
  exit 1
fi

if [ ! -d "$ENGINE_SRC" ]; then
  echo "Could not find the engine/ directory at $ENGINE_SRC." >&2
  echo "This script expects to run from a full repo checkout (frontends/freepbx" >&2
  echo "and engine/ as siblings under the repo root), not a standalone copy." >&2
  exit 1
fi

if [ "$SOURCE_DIR" = "$STAGING_DIR" ]; then
  # The staging step below deletes and recreates $STAGING_DIR (and this script
  # deletes it again at the end), so running from inside it would destroy the
  # source being installed.
  echo "Do not run install.sh from inside $STAGING_DIR - it is the script's own" >&2
  echo "temporary staging directory. Run it from your source checkout instead." >&2
  exit 1
fi

FREEPBX_MAJOR="$(fwconsole --version 2>/dev/null | grep -Eo '[0-9]+' | head -n 1 || true)"
if [ "$FREEPBX_MAJOR" != "16" ] && [ "$FREEPBX_MAJOR" != "17" ]; then
  echo "ERROR: supported FreePBX major versions are 16 and 17; detected '${FREEPBX_MAJOR:-unknown}'." >&2
  echo "       No installation files were changed." >&2
  exit 1
fi
if ! command -v php >/dev/null 2>&1; then
  echo "ERROR: no php-cli interpreter found on \$PATH; no installation files were changed." >&2
  exit 1
fi
PHP_BIN="$(command -v php)"
PHP_VERSION_ID="$($PHP_BIN -r 'echo PHP_VERSION_ID;')"
if [ "$PHP_VERSION_ID" -lt 70400 ]; then
  echo "ERROR: PHP 7.4 or newer is required; no installation files were changed." >&2
  exit 1
fi
for extension in curl json zlib; do
  if ! "$PHP_BIN" -r "exit(extension_loaded('$extension') ? 0 : 1);"; then
    echo "ERROR: required PHP extension is missing: $extension; no installation files were changed." >&2
    exit 1
  fi
done
"$PHP_BIN" "$SOURCE_DIR/patch-callrecording.php" verify \
  /var/www/html/admin/modules/callrecording/functions.inc.php "$FREEPBX_MAJOR" "$STATE_DIR"

if [ ! -x "$SOURCE_DIR/backup-installation.sh" ]; then
  echo "ERROR: mandatory installation backup helper is missing or not executable." >&2
  echo "       No installation files were changed." >&2
  exit 1
fi
echo "==> Creating mandatory pre-installation backup"
INSTALL_BACKUP_DIR="$("$SOURCE_DIR/backup-installation.sh")"
export SEDA_SANJ_PREINSTALL_BACKUP_DIR="$INSTALL_BACKUP_DIR"
echo "    Backup created at: $INSTALL_BACKUP_DIR"

echo "==> Checking for an existing installation"
PREV_INSTALL=false
if [ -d "$MODULE_DIR" ] || fwconsole ma list 2>/dev/null | grep -qi "\b${MODULE_RAWNAME}\b"; then
  PREV_INSTALL=true
  echo "    Existing installation detected - this will be treated as an upgrade."
  echo "    config.ini, state, spool, and logs will be left in place."
else
  echo "    No existing installation found - proceeding with a fresh install."
fi

SERVICE_WAS_RUNNING=false
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  SERVICE_WAS_RUNNING=true
fi

echo "==> Staging module source at $STAGING_DIR (temporary)"
rm -rf "$STAGING_DIR"
cp -r "$SOURCE_DIR" "$STAGING_DIR"
# Bundle the host-agnostic engine into the module's own directory, so the
# deployed module (and any release zip built from this staging copy) is
# fully self-contained - Recuploader.class.php expects __DIR__ . '/engine'
# to exist inside its own directory.
if [ "$ENGINE_SRC" != "$SOURCE_DIR/engine" ]; then
  cp -r "$ENGINE_SRC" "$STAGING_DIR/engine"
fi
chown -R asterisk:asterisk "$STAGING_DIR"
chmod -R a+rX "$STAGING_DIR"

echo "==> Deploying to $MODULE_DIR"
# Fully replace rather than merge, so a file removed/renamed in a newer
# version doesn't linger from a previous install.
rm -rf "$MODULE_DIR"
cp -r "$STAGING_DIR" "$MODULE_DIR"
chown -R asterisk:asterisk "$MODULE_DIR"

echo "==> Registering module with FreePBX"
# Best-effort first (documented path); known not to work in every
# environment, so we don't depend on its success.
fwconsole ma installlocal "$STAGING_DIR" >/dev/null 2>&1 || true

if fwconsole ma list 2>/dev/null | grep -qi "\b${MODULE_RAWNAME}\b"; then
  echo "    Module already registered - re-running install to pick up changes."
else
  echo "    Registering module for the first time."
fi
fwconsole ma install "$MODULE_RAWNAME"

echo "==> Directories"
mkdir -p "$BIN_DIR" "$CONF_DIR" "$STATE_DIR" \
         "$SPOOL_DIR/pending" "$SPOOL_DIR/failed" "$SPOOL_DIR/uploaded" \
         "$LOG_DIR"
chown -R asterisk:asterisk "$BIN_DIR" "$CONF_DIR" "$STATE_DIR" "$SPOOL_DIR" "$LOG_DIR"
chmod 750 "$CONF_DIR"
touch "$LOG_DIR/uploader.log"
chown asterisk:asterisk "$LOG_DIR/uploader.log"
chmod 640 "$LOG_DIR/uploader.log"
rmdir "$SPOOL_DIR/staging" 2>/dev/null || true

echo "==> PHP engine"
# Deploy engine/ verbatim (autoload.php, src/, bin/, config/ at BIN_DIR's
# top level - the engine's own path resolution, e.g. Staging::engineRoot(),
# assumes bin/7zip sits next to src/, so this must not be flattened or
# renamed).
rm -rf "${BIN_DIR:?}"/*
cp -r "$MODULE_DIR/engine/." "$BIN_DIR/"
chown -R asterisk:asterisk "$BIN_DIR"
chmod -R a+rX "$BIN_DIR"
chmod 755 "$BIN_DIR"/bin/*.php
find "$BIN_DIR/bin/7zip" "$BIN_DIR/bin/ffmpeg" "$BIN_DIR/bin/gsm" -type f -exec chmod 755 {} \; 2>/dev/null || true
if ! diff -qr "$MODULE_DIR/engine" "$BIN_DIR" >/dev/null; then
  echo "ERROR: deployed uploader engine does not match the module release." >&2
  echo "       The service was not restarted with a mixed runtime." >&2
  exit 1
fi
echo "    Verified deployed engine matches the module release"

echo "==> Checking system dependencies (php-cli, curl/sqlite extensions, ffmpeg, gsm encoder)"
# This script does NOT attempt to install php itself - FreePBX itself
# already requires php-cli + php-curl, so on a real FreePBX box this is
# normally already satisfied. It only checks for what's actually needed
# and tells you what to install by hand if something is missing.
#
# service.php (via the systemd unit) and mix-stereo.php (via MIXMON_POST)
# both resolve php through $PATH at the moment they run (command -v php),
# rather than a path hardcoded here - it is not always at /usr/bin/php.
# Check now so a missing interpreter fails loudly here instead of silently
# as a broken service/upload later.
if ! command -v php >/dev/null 2>&1; then
  echo "ERROR: no php-cli interpreter found on \$PATH. Install php-cli via your distro's package" >&2
  echo "       manager (e.g. 'apt-get install php-cli', 'dnf install php-cli') so it is on \$PATH," >&2
  echo "       then re-run install.sh." >&2
  exit 1
fi
echo "    php found at: $PHP_BIN"
echo "    PHP version and curl/json/zlib extensions are available"

# archive.format encoding for any format OTHER than gsm (mp3, ogg, opus,
# ...) shells out to ffmpeg, resolved in this order: ARU_FFMPEG_PATH env
# var, then a vendored bin/ffmpeg/ffmpeg-<arch> binary, then $PATH.
# archive.format = gsm (the default) never touches ffmpeg - see the next
# check below - because ffmpeg can only encode GSM via an external
# --enable-libgsm build option that essentially no pre-built static
# ffmpeg distribution turns on.
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ARCH_TAG=x86_64 ;;
  aarch64|arm64) ARCH_TAG=aarch64 ;;
  *) ARCH_TAG="$ARCH" ;;
esac
if [ -x "$BIN_DIR/bin/ffmpeg/ffmpeg-$ARCH_TAG" ]; then
  echo "    Using vendored ffmpeg at bin/ffmpeg/ffmpeg-$ARCH_TAG"
elif command -v ffmpeg >/dev/null 2>&1; then
  echo "    Using system ffmpeg: $(command -v ffmpeg)"
else
  echo "WARNING: ffmpeg not found on \$PATH and no vendored binary at" >&2
  echo "         bin/ffmpeg/ffmpeg-$ARCH_TAG - archive.format values other than" >&2
  echo "         gsm (mp3, ogg, opus, ...) will fail at upload time until either" >&2
  echo "         is installed (e.g. 'apt-get install ffmpeg', 'dnf install ffmpeg'," >&2
  echo "         or vendor a static build)." >&2
fi

# archive.format = gsm (the default) uses a dedicated encoder instead,
# resolved in this order: ARU_GSM_ENCODER_PATH env var, then a vendored
# bin/gsm/gsm-encode-<arch> binary, then gsm-encode/toast on $PATH.
if [ -x "$BIN_DIR/bin/gsm/gsm-encode-$ARCH_TAG" ]; then
  echo "    Using vendored GSM encoder at bin/gsm/gsm-encode-$ARCH_TAG"
elif command -v gsm-encode >/dev/null 2>&1; then
  echo "    Using system gsm-encode: $(command -v gsm-encode)"
elif command -v toast >/dev/null 2>&1; then
  echo "    Using system toast (gsm-utils package): $(command -v toast)"
else
  echo "WARNING: no GSM encoder found - no vendored bin/gsm/gsm-encode-$ARCH_TAG," >&2
  echo "         no gsm-encode or toast on \$PATH. archive.format = gsm (the" >&2
  echo "         default) will fail at upload time until you either run" >&2
  echo "         bin/gsm/build.sh on a $ARCH_TAG box (needs libgsm1-dev + gcc), or" >&2
  echo "         'apt-get install gsm-utils' for the system toast fallback." >&2
fi

echo "==> Refreshing MixMonitor globals (the module's one recording path -"
echo "    MONITOR_REC_OPTION/MIXMON_POST via bin/mix-stereo.php) -"
echo "    module install() skips this once the marker block already"
echo "    exists, so it's done explicitly here to pick up any changes"
if [ -f "$GLOBALS_FILE" ] && grep -qF "$MIXMON_MARKER_BEGIN" "$GLOBALS_FILE"; then
  sed -i "/$(printf '%s' "$MIXMON_MARKER_BEGIN" | sed 's/[.[\*^$/]/\\&/g')/,/$(printf '%s' "$MIXMON_MARKER_END" | sed 's/[.[\*^$/]/\\&/g')/d" \
    "$GLOBALS_FILE"
fi
if [ -f "$MODULE_DIR/dialplan/globals-custom-mixmon.conf" ]; then
  cat "$MODULE_DIR/dialplan/globals-custom-mixmon.conf" >> "$GLOBALS_FILE"
fi

echo "==> Applying verified FreePBX callrecording fixture patch"
PATCH_STATE_EXISTED=false
if [ -f "$STATE_DIR/core-patch.json" ]; then
  PATCH_STATE_EXISTED=true
fi
"$PHP_BIN" "$MODULE_DIR/patch-callrecording.php" apply \
  /var/www/html/admin/modules/callrecording/functions.inc.php "$FREEPBX_MAJOR" "$STATE_DIR"
if [ "$PATCH_STATE_EXISTED" = false ]; then
  trap '"$PHP_BIN" "$MODULE_DIR/patch-callrecording.php" restore /var/www/html/admin/modules/callrecording/functions.inc.php 0 "$STATE_DIR" || true' ERR
fi

echo "==> Cleaning up any leftover pre-1.0.0 dialplan hook (retired - mixmon"
echo "    is the only supported recording path now; this is one-way and"
echo "    never re-adds the block)"
if [ -f "$LEGACY_DIALPLAN_FILE" ] && grep -qF "$LEGACY_MARKER_BEGIN" "$LEGACY_DIALPLAN_FILE"; then
  sed -i "/$(printf '%s' "$LEGACY_MARKER_BEGIN" | sed 's/[.[\*^$/]/\\&/g')/,/$(printf '%s' "$LEGACY_MARKER_END" | sed 's/[.[\*^$/]/\\&/g')/d" \
    "$LEGACY_DIALPLAN_FILE"
  echo "    Removed a leftover block from an older install."
fi

echo "==> Default config (only if missing)"
if [ ! -f "$CONF_DIR/config.ini" ]; then
  install -m 640 "$MODULE_DIR/engine/config/config.ini.example" "$CONF_DIR/config.ini"
fi
chown asterisk:asterisk "$CONF_DIR/config.ini" 2>/dev/null || true
chmod 640 "$CONF_DIR/config.ini"

echo "==> systemd unit"
install -m 644 "$MODULE_DIR/systemd/asterisk-recording-uploader.service" \
  /etc/systemd/system/asterisk-recording-uploader.service
systemctl daemon-reload

echo "==> sudoers drop-in (lets the FreePBX GUI restart just this service)"
cat > /etc/sudoers.d/asterisk-recording-uploader <<'EOF'
asterisk ALL=(root) NOPASSWD: /bin/systemctl start asterisk-recording-uploader.service, /bin/systemctl stop asterisk-recording-uploader.service, /bin/systemctl restart asterisk-recording-uploader.service, /bin/systemctl enable asterisk-recording-uploader.service, /bin/systemctl disable asterisk-recording-uploader.service, /bin/systemctl status asterisk-recording-uploader.service
EOF
chmod 440 /etc/sudoers.d/asterisk-recording-uploader

echo "==> Reloading FreePBX/Asterisk (applies the MixMonitor globals)"
fwconsole reload || asterisk -rx "dialplan reload" || true

echo "==> Service"
systemctl enable "$SERVICE_NAME"
if [ "$PREV_INSTALL" = true ] || [ "$SERVICE_WAS_RUNNING" = true ]; then
  echo "    Restarting $SERVICE_NAME so it picks up the new/changed code"
  systemctl restart "$SERVICE_NAME"
else
  systemctl start "$SERVICE_NAME"
fi

echo "==> Removing the temporary staging copy $STAGING_DIR (not needed once installed)"
rm -rf "$STAGING_DIR"
trap - ERR

echo ""
echo "==> Done."
fwconsole ma list 2>/dev/null | grep -i "$MODULE_RAWNAME" || true
systemctl --no-pager status "$SERVICE_NAME" 2>/dev/null | head -n 5 || true
echo ""
if [ "$PREV_INSTALL" = true ]; then
  echo "Upgrade complete. config.ini was left as-is; new settings already take effect via their built-in defaults, but"
  echo "open Admin > Seda Sanj and click 'Save & restart service' once if you"
  echo "want them written out to config.ini explicitly."
else
  echo "Install complete. Open Admin > Seda Sanj in FreePBX to set your"
  echo "endpoint/API key and the ASR model(s) to use."
fi
