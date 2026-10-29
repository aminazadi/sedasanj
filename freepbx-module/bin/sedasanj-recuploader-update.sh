#!/bin/bash
#
# sedasanj-recuploader-update - root helper that applies a downloaded,
# signed recuploader release. Installed by Recuploader::installUpdateHelper()
# (and install.sh) as /usr/local/sbin/sedasanj-recuploader-update, root-owned
# 0755, and allowed for the asterisk user in the module's sudoers drop-in.
#
# Usage: sedasanj-recuploader-update <32-hex job id>
#
# The FreePBX page (running as asterisk) has already downloaded and checked
# /var/spool/asterisk-recording-uploader/updates/<job>/{release.zip,job.json}.
# That directory is asterisk-writable, so everything is copied into a
# root-only work directory and verified again here against the root-owned
# signing key before anything is touched:
#
#   verify  -> extract -> backup -> swap -> install -> reload -> health -> report
#
# Progress goes to /var/lib/sedasanj-recuploader-update/jobs/<job>/status.json
# ({state, step, steps[], percent, log_tail, ...}), which the page polls. A
# failure after the module directory was swapped rolls back: the previous
# tree is moved back, the pre-update backup is restored and the previous
# version is re-registered with fwconsole.

set -uo pipefail
umask 022
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C

JOB="${1:-}"
if ! [[ "$JOB" =~ ^[a-f0-9]{32}$ ]]; then
  echo "usage: $0 <32-hex job id>" >&2
  exit 2
fi
if [ "$EUID" -ne 0 ]; then
  echo "ERROR: must run as root" >&2
  exit 1
fi

SELF=/usr/local/sbin/sedasanj-recuploader-update
[ -x "$SELF" ] || SELF="$(readlink -f "$0")"

MODULE_NAME=recuploader
MODULES_DIR=/var/www/html/admin/modules
MODULE_DIR="$MODULES_DIR/$MODULE_NAME"
PREV_DIR="$MODULES_DIR/.$MODULE_NAME.prev"
SPOOL_JOB_DIR="/var/spool/asterisk-recording-uploader/updates/$JOB"
STATE_ROOT=/var/lib/sedasanj-recuploader-update
STATUS_DIR="$STATE_ROOT/jobs/$JOB"
WORK="$STATE_ROOT/work/$JOB"
PUBKEY=/etc/sedasanj-recuploader-update/release-signing.pub
CONFIG_INI=/etc/asterisk-recording-uploader/config.ini
SERVICE_NAME=asterisk-recording-uploader.service
MAX_BYTES=209715200
TIMEOUT_SECONDS=900
ROLLBACK_SECONDS=600
KEEP_JOBS=2

# Leave the web server's cgroup so restarting httpd/php-fpm mid-update
# cannot kill us; fall back to running inline where systemd-run is missing
# or too old for --collect.
if [ -z "${SJ_UPDATE_DETACHED:-}" ] && [ -d /run/systemd/system ] && command -v systemd-run >/dev/null 2>&1; then
  unit="sedasanj-recuploader-update-${JOB:0:12}"
  if systemd-run --quiet --collect --unit="$unit" --setenv=SJ_UPDATE_DETACHED=1 "$SELF" "$JOB" 2>/dev/null \
    || systemd-run --quiet --unit="$unit" --setenv=SJ_UPDATE_DETACHED=1 "$SELF" "$JOB"; then
    exit 0
  fi
fi

install -d -o root -g root -m 0755 "$STATE_ROOT" "$STATE_ROOT/jobs" "$STATUS_DIR"
install -d -o root -g root -m 0700 "$STATE_ROOT/work"
rm -rf -- "$WORK"
install -d -o root -g root -m 0700 "$WORK"
LOG="$STATUS_DIR/update.log"
: > "$LOG"
chmod 0644 "$LOG"

STEPS=(verify extract backup swap install activate reload health report)
declare -A STEP_STATE
for s in "${STEPS[@]}"; do STEP_STATE[$s]=pending; done
STATE=running
CUR_STEP=""
MESSAGE=""
RELEASE_ID=""
TO_VERSION=""
FROM_VERSION=""
HOST_UUID=""
BACKUP_DIR=""
SWAPPED=0
START_EPOCH=$(date +%s)
DEADLINE=$((START_EPOCH + TIMEOUT_SECONDS))

log() {
  printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*" >> "$LOG"
}

# All JSON handling and signature checks run through this small PHP file,
# written fresh into the root-only work directory (never loaded from the
# asterisk-writable module tree).
LIB="$WORK/lib.php"
cat > "$LIB" <<'PHP'
<?php
$cmd = $argv[1] ?? '';
$a = array_slice($argv, 2);
function fail($m) { fwrite(STDERR, $m . "\n"); exit(1); }
switch ($cmd) {
case 'job':
    $j = json_decode((string) @file_get_contents($a[0]), true);
    if (!is_array($j)) { fail('job.json is unreadable'); }
    $checks = array(
        'release_id' => '/^[A-Za-z0-9_-]{1,64}$/',
        'version' => '/^\d+\.\d+\.\d+$/',
        'from_version' => '/^(\d+\.\d+\.\d+)?$/',
        'sha256' => '/^[a-f0-9]{64}$/',
        'signature' => '/^[A-Za-z0-9+\/]{86}==$/',
        'host_uuid' => '/^[0-9a-f-]{36}$/',
        'manifest' => '/^\{[\x20-\x7e]{2,2000}\}$/',
        'manifest_signature' => '/^[A-Za-z0-9+\/]{86}==$/',
    );
    foreach ($checks as $k => $re) {
        $v = (string) ($j[$k] ?? '');
        if (!preg_match($re, $v)) { fail("job.json field {$k} is invalid"); }
        echo $v, "\n";
    }
    break;
case 'verify':
    list($zip, $sha, $sig, $pubFile, $manifest, $manifestSig, $toVersion) = $a;
    if (!function_exists('sodium_crypto_sign_verify_detached')) { fail('PHP sodium extension is missing'); }
    // One public key per line; several lines allow a key rotation (old and new key valid together).
    $lines = array_values(array_filter(array_map('trim', file($pubFile) ?: array()), function ($l) { return $l !== '' && $l[0] !== '#'; }));
    $keys = array();
    foreach ($lines as $l) { $k = base64_decode($l, true); if ($k !== false && strlen($k) === 32) { $keys[] = $k; } }
    if (!$keys || count($keys) !== count($lines) || count($keys) > 3) { fail('Release signing key is not configured on this server'); }
    $actual = hash_file('sha256', $zip);
    if (!hash_equals($sha, (string) $actual)) { fail('Release checksum does not match'); }
    $raw = base64_decode($sig, true);
    $okDigest = false;
    foreach ($keys as $k) { if ($raw !== false && strlen($raw) === 64 && sodium_crypto_sign_verify_detached($raw, $actual, $k)) { $okDigest = true; } }
    if (!$okDigest) { fail('Release signature is invalid'); }
    // The signed manifest binds version, digest, size and an expiry to this exact download.
    $mraw = base64_decode($manifestSig, true);
    $okManifest = false;
    foreach ($keys as $k) {
        if ($mraw !== false && strlen($mraw) === 64 && sodium_crypto_sign_verify_detached($mraw, "sedasanj-module-manifest-v1\n" . $manifest, $k)) { $okManifest = true; }
    }
    if (!$okManifest) { fail('Release manifest signature is invalid'); }
    $m = json_decode($manifest, true);
    if (!is_array($m)) { fail('Release manifest is unreadable'); }
    if (($m['rawname'] ?? '') !== 'recuploader') { fail('Release manifest is for another module'); }
    if (($m['version'] ?? '') !== $toVersion) { fail('Release manifest version does not match the job'); }
    if (!hash_equals((string) ($m['sha256'] ?? ''), $actual)) { fail('Release manifest digest does not match the download'); }
    if ((int) ($m['size'] ?? -1) !== filesize($zip)) { fail('Release manifest size does not match the download'); }
    $expires = strtotime((string) ($m['expires_at'] ?? ''));
    $issued = strtotime((string) ($m['issued_at'] ?? ''));
    if ($expires === false || $expires < time()) { fail('SS-UPD-1002: release manifest has expired'); }
    if ($issued === false || $issued > time() + 600) { fail('Release manifest is dated in the future (check the PBX clock)'); }
    echo "ok\n";
    break;
case 'zipnames':
    // Fallback listing/extraction when unzip is unavailable.
    if (!class_exists('ZipArchive')) { fail('Neither unzip nor PHP zip is available'); }
    $z = new ZipArchive();
    if ($z->open($a[0]) !== true) { fail('Release zip cannot be opened'); }
    for ($i = 0; $i < $z->numFiles; $i++) {
        $opsys = 0; $attr = 0;
        $z->getExternalAttributesIndex($i, $opsys, $attr);
        if ($opsys === ZipArchive::OPSYS_UNIX && ((($attr >> 16) & 0170000) === 0120000)) { fail('Release zip contains a symlink'); }
        echo $z->getNameIndex($i), "\n";
    }
    if (($a[1] ?? '') !== '' && !$z->extractTo($a[1])) { fail('Release zip extraction failed'); }
    break;
case 'modxml':
    $x = @simplexml_load_file($a[0]);
    if ($x === false) { fail('module.xml is unreadable'); }
    echo trim((string) $x->rawname), "\n", trim((string) $x->version), "\n";
    break;
case 'newer':
    // exit 0 only when $a[0] is strictly newer than $a[1]: blocks downgrades and replays of old signed releases.
    exit(version_compare($a[0], $a[1], '>') ? 0 : 1);
case 'status':
    list($out, $job, $state, $step, $from, $to, $message, $logFile) = array_slice($a, 0, 8);
    $steps = array(); $done = 0;
    foreach (array_slice($a, 8) as $pair) {
        list($id, $st) = explode('=', $pair, 2);
        $steps[] = array('id' => $id, 'state' => $st);
        $done += ($st === 'done' || $st === 'skipped') ? 1 : ($st === 'running' ? 0.5 : 0);
    }
    $percent = $state === 'succeeded' ? 100 : (int) floor(100 * $done / max(1, count($steps)));
    $tail = array_slice(file($logFile, FILE_IGNORE_NEW_LINES) ?: array(), -60);
    $data = array('job' => $job, 'state' => $state, 'step' => $step, 'steps' => $steps, 'percent' => $percent,
        'from_version' => $from, 'to_version' => $to, 'message' => $message,
        'log_tail' => implode("\n", $tail), 'updated_at' => time());
    file_put_contents($out, json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE));
    break;
case 'report':
    list($ini, $hostUuid, $releaseId, $from, $to, $status, $message) = $a;
    $p = @parse_ini_file($ini, true, INI_SCANNER_RAW);
    if (!is_array($p)) { fail('config.ini is unreadable'); }
    $g = $p['general'] ?? array();
    $endpoint = ($g['endpoint_b64'] ?? '') !== '' ? base64_decode($g['endpoint_b64'], true) : ($g['endpoint'] ?? '');
    $key = ($g['api_key_b64'] ?? '') !== '' ? base64_decode($g['api_key_b64'], true) : ($g['api_key'] ?? '');
    $url = preg_replace('#/calls/?$#', '/module/update-report', (string) $endpoint);
    if (!is_string($url) || $url === $endpoint || (string) $key === '') { fail('Ingest endpoint or API key is not configured'); }
    $verify = !in_array(strtolower((string) ($g['verify_tls'] ?? 'true')), array('false', '0', 'no', 'off'), true);
    $header = ($g['auth_header'] ?? 'Authorization') . ': ' . trim(($g['auth_scheme'] ?? 'Bearer') . ' ' . $key);
    $body = json_encode(array('host_uuid' => $hostUuid, 'release_id' => $releaseId, 'from_version' => $from,
        'to_version' => $to, 'status' => $status, 'message' => substr($message, 0, 2000)), JSON_INVALID_UTF8_SUBSTITUTE);
    $ch = curl_init($url);
    curl_setopt_array($ch, array(CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body, CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => array($header, 'Content-Type: application/json', 'Accept: application/json'),
        CURLOPT_TIMEOUT => 15, CURLOPT_SSL_VERIFYPEER => $verify, CURLOPT_SSL_VERIFYHOST => $verify ? 2 : 0));
    $res = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    if ($res === false || $code < 200 || $code >= 300) { fail('update-report failed: ' . ($res === false ? curl_error($ch) : "HTTP {$code}")); }
    echo "ok\n";
    break;
default:
    fail("unknown command {$cmd}");
}
PHP

PHP_BIN="$(command -v php || true)"

write_status() {
  [ -n "$PHP_BIN" ] || return 0
  local pairs=() s tmp
  for s in "${STEPS[@]}"; do pairs+=("$s=${STEP_STATE[$s]}"); done
  tmp="$(mktemp "$STATUS_DIR/.status.XXXXXX")" || return 0
  if "$PHP_BIN" "$LIB" status "$tmp" "$JOB" "$STATE" "$CUR_STEP" "$FROM_VERSION" "$TO_VERSION" "$MESSAGE" "$LOG" "${pairs[@]}" 2>>"$LOG"; then
    chmod 0644 "$tmp"
    mv -f "$tmp" "$STATUS_DIR/status.json"
  else
    rm -f "$tmp"
  fi
}

begin_step() {
  CUR_STEP="$1"
  STEP_STATE[$1]=running
  log "==> $1"
  write_status
}

end_step() {
  STEP_STATE[$CUR_STEP]="${1:-done}"
  write_status
}

remaining() {
  local left=$((DEADLINE - $(date +%s)))
  [ "$left" -gt 5 ] && echo "$left" || echo 5
}

# Runs a command with output in the log, bounded by the global deadline.
run() {
  log "\$ $*"
  timeout --kill-after=15 "$(remaining)" "$@" >> "$LOG" 2>&1
  local rc=$?
  [ "$rc" -eq 124 ] && log "timed out"
  return "$rc"
}

report() {
  [ -n "$RELEASE_ID" ] && [ -n "$PHP_BIN" ] || return 1
  timeout 30 "$PHP_BIN" "$LIB" report "$CONFIG_INI" "$HOST_UUID" "$RELEASE_ID" "$FROM_VERSION" "$TO_VERSION" "$1" "$2" >> "$LOG" 2>&1
}

installed_version() {
  fwconsole ma list 2>/dev/null | awk -F'|' -v m="$MODULE_NAME" '{n=$2; v=$3; gsub(/ /,"",n); gsub(/ /,"",v); if (n==m) print v}' | head -n 1
}

prune_jobs() {
  local dir
  for root in "$STATE_ROOT/jobs" "$STATE_ROOT/work" /var/spool/asterisk-recording-uploader/updates; do
    [ -d "$root" ] || continue
    ls -1t "$root" 2>/dev/null | grep -E '^[a-f0-9]{32}$' | tail -n +$((KEEP_JOBS + 1)) | while read -r dir; do
      rm -rf -- "${root:?}/$dir"
    done
  done
}

rollback() {
  DEADLINE=$(($(date +%s) + ROLLBACK_SECONDS))
  local ok=1
  log "==> rollback"
  if [ -d "$PREV_DIR" ]; then
    rm -rf -- "$MODULE_DIR"
    mv -- "$PREV_DIR" "$MODULE_DIR" || ok=0
  fi
  # Prefer the restore script of the version we just put back; the new package's copy is the fallback.
  RESTORE_SCRIPT="$MODULE_DIR/restore-installation-backup.sh"
  [ -f "$RESTORE_SCRIPT" ] || RESTORE_SCRIPT="$WORK/restore-installation-backup.sh"
  if [ -n "$BACKUP_DIR" ] && [ -f "$RESTORE_SCRIPT" ]; then
    run bash "$RESTORE_SCRIPT" "$BACKUP_DIR" || ok=0
    SEDA_SANJ_PREINSTALL_BACKUP_DIR="$BACKUP_DIR" run fwconsole ma install "$MODULE_NAME" || ok=0
    run fwconsole chown || true
    run fwconsole reload || ok=0
  else
    ok=0
  fi
  [ "$ok" -eq 1 ]
}

fail() {
  MESSAGE="$1"
  log "ERROR: $1"
  [ -n "$CUR_STEP" ] && STEP_STATE[$CUR_STEP]=failed
  if [ "$SWAPPED" -eq 1 ]; then
    STATE=running
    write_status
    if rollback; then
      STATE=rolled_back
      MESSAGE="$1 - the previous version was restored"
    else
      STATE=failed
      MESSAGE="$1 - rollback was incomplete, restore manually from ${BACKUP_DIR:-the latest backup in /var/backups/sedasanj-recuploader}"
    fi
  else
    STATE=failed
  fi
  log "$MESSAGE"
  write_status
  report "$STATE" "$MESSAGE" || true
  prune_jobs
  exit 1
}

if [ -z "$PHP_BIN" ]; then
  log "ERROR: php CLI not found"
  exit 1
fi

exec 9> "$STATE_ROOT/.lock"
if ! flock -n 9; then
  fail "Another update is already running"
fi

# ---- 1. verify ---------------------------------------------------------------
begin_step verify
for f in job.json release.zip; do
  if [ -L "$SPOOL_JOB_DIR/$f" ] || [ ! -f "$SPOOL_JOB_DIR/$f" ]; then
    fail "Update job file $f is missing"
  fi
  cp -P -- "$SPOOL_JOB_DIR/$f" "$WORK/$f" || fail "Cannot copy $f"
  [ -f "$WORK/$f" ] && [ ! -L "$WORK/$f" ] || fail "Update job file $f is not a regular file"
done
size=$(stat -c %s "$WORK/release.zip" 2>/dev/null || echo 0)
if [ "$size" -le 0 ] || [ "$size" -gt "$MAX_BYTES" ]; then
  fail "Release archive has an invalid size"
fi
mapfile -t job_fields < <("$PHP_BIN" "$LIB" job "$WORK/job.json" 2>>"$LOG")
[ "${#job_fields[@]}" -eq 8 ] || fail "job.json is invalid (a signed manifest is required)"
RELEASE_ID="${job_fields[0]}"
TO_VERSION="${job_fields[1]}"
FROM_VERSION="${job_fields[2]}"
SHA256="${job_fields[3]}"
SIGNATURE="${job_fields[4]}"
HOST_UUID="${job_fields[5]}"
MANIFEST="${job_fields[6]}"
MANIFEST_SIGNATURE="${job_fields[7]}"
log "Updating $MODULE_NAME ${FROM_VERSION:-?} -> $TO_VERSION (release $RELEASE_ID)"
"$PHP_BIN" "$LIB" verify "$WORK/release.zip" "$SHA256" "$SIGNATURE" "$PUBKEY" "$MANIFEST" "$MANIFEST_SIGNATURE" "$TO_VERSION" >> "$LOG" 2>&1 \
  || fail "Release signature or checksum verification failed"
CURRENT_VERSION=""
if [ -f "$MODULE_DIR/module.xml" ]; then
  CURRENT_VERSION="$("$PHP_BIN" "$LIB" modxml "$MODULE_DIR/module.xml" 2>/dev/null | sed -n 2p)"
fi
if [ -n "$CURRENT_VERSION" ] && ! "$PHP_BIN" "$LIB" newer "$TO_VERSION" "$CURRENT_VERSION"; then
  fail "SS-UPD-1004: refusing to install $TO_VERSION over $CURRENT_VERSION (only newer releases are installed automatically)"
fi
end_step

# ---- 2. extract --------------------------------------------------------------
begin_step extract
EXTRACT="$WORK/extract"
install -d -m 0700 "$EXTRACT"
if command -v unzip >/dev/null 2>&1; then
  names="$(unzip -Z1 "$WORK/release.zip" 2>>"$LOG")" || fail "Release archive is unreadable"
  if unzip -Z "$WORK/release.zip" 2>/dev/null | grep -q '^l'; then
    fail "Release archive contains a symlink"
  fi
else
  names="$("$PHP_BIN" "$LIB" zipnames "$WORK/release.zip" 2>>"$LOG")" || fail "Release archive is unreadable"
fi
while IFS= read -r name; do
  [ -n "$name" ] || continue
  case "$name" in
    "$MODULE_NAME"/*) ;;
    *) fail "Release archive contains an entry outside $MODULE_NAME/: $name" ;;
  esac
  case "/$name/" in
    */../*|*/./*|*\\*) fail "Release archive contains an unsafe path: $name" ;;
  esac
done <<< "$names"
if command -v unzip >/dev/null 2>&1; then
  run unzip -q "$WORK/release.zip" -d "$EXTRACT" || fail "Release archive extraction failed"
else
  "$PHP_BIN" "$LIB" zipnames "$WORK/release.zip" "$EXTRACT" > /dev/null 2>>"$LOG" || fail "Release archive extraction failed"
fi
if [ -n "$(find "$EXTRACT" -type l -print -quit)" ]; then
  fail "Release archive contains a symlink"
fi
if [ "$(ls -A "$EXTRACT")" != "$MODULE_NAME" ]; then
  fail "Release archive must contain only the $MODULE_NAME/ directory"
fi
PKG="$EXTRACT/$MODULE_NAME"
mapfile -t xml_fields < <("$PHP_BIN" "$LIB" modxml "$PKG/module.xml" 2>>"$LOG")
if [ "${xml_fields[0]:-}" != "$MODULE_NAME" ] || [ "${xml_fields[1]:-}" != "$TO_VERSION" ]; then
  fail "module.xml does not match release $TO_VERSION (found ${xml_fields[0]:-?} ${xml_fields[1]:-?})"
fi
for f in backup-installation.sh restore-installation-backup.sh; do
  [ -f "$PKG/$f" ] || fail "Release archive is missing $f"
done
cp -- "$PKG/restore-installation-backup.sh" "$WORK/restore-installation-backup.sh"
chown -R root:root "$PKG"
end_step

# ---- 3. backup ---------------------------------------------------------------
begin_step backup
backup_out="$WORK/backup.out"
timeout --kill-after=15 "$(remaining)" bash "$PKG/backup-installation.sh" > "$backup_out" 2>>"$LOG" \
  || fail "Pre-update backup failed"
BACKUP_DIR="$(tail -n 1 "$backup_out")"
case "$BACKUP_DIR" in
  /var/backups/sedasanj-recuploader/*) [ -d "$BACKUP_DIR" ] || fail "Backup directory is missing" ;;
  *) fail "Backup did not report a valid directory" ;;
esac
log "Backup: $BACKUP_DIR"
end_step

# ---- 4. swap -----------------------------------------------------------------
begin_step swap
rm -rf -- "$PREV_DIR"
if [ -d "$MODULE_DIR" ]; then
  mv -- "$MODULE_DIR" "$PREV_DIR" || fail "Cannot move the current module aside"
fi
SWAPPED=1
mv -- "$PKG" "$MODULE_DIR" || fail "Cannot move the new module into place"
chown -R asterisk:asterisk "$MODULE_DIR" 2>>"$LOG" || true
end_step

# ---- 5. install --------------------------------------------------------------
begin_step install
SEDA_SANJ_PREINSTALL_BACKUP_DIR="$BACKUP_DIR" run fwconsole ma install "$MODULE_NAME" \
  || fail "fwconsole ma install failed"
end_step

# ---- 5b. activate -----------------------------------------------------------
# fwconsole may drop to the asterisk user, in which case install() only registered the module.
# Run the module's own root provisioning explicitly so a real update always ends fully activated,
# restarts the service on the new code and refreshes the hook globals.
begin_step activate
SEDA_SANJ_PREINSTALL_BACKUP_DIR="$BACKUP_DIR" run "$PHP_BIN" -d display_errors=stderr -r '
  $_SERVER["HTTP_HOST"] = "localhost";
  require "/etc/freepbx.conf";
  \FreePBX::Create()->Recuploader->provision();
' || fail "SS-UPD-1005: module activation (root provisioning) failed"
end_step

# ---- 6. reload ---------------------------------------------------------------
begin_step reload
run fwconsole chown || log "fwconsole chown reported an error (continuing)"
run fwconsole reload || fail "fwconsole reload failed"
end_step

# ---- 7. health ---------------------------------------------------------------
begin_step health
active=0
for _ in $(seq 1 15); do
  if systemctl is-active --quiet "$SERVICE_NAME"; then active=1; break; fi
  sleep 2
done
[ "$active" -eq 1 ] || fail "$SERVICE_NAME is not active after the update"
registered="$(installed_version)"
log "FreePBX reports $MODULE_NAME $registered; files are $TO_VERSION"
[ "$registered" = "$TO_VERSION" ] || fail "FreePBX registered version ${registered:-unknown} instead of $TO_VERSION"
end_step

# ---- 8. report ---------------------------------------------------------------
STATE=succeeded
MESSAGE="Updated to $TO_VERSION"
begin_step report
if report succeeded "$MESSAGE"; then
  end_step done
else
  log "Could not report the result to the update server (the update itself succeeded)"
  end_step skipped
fi
CUR_STEP=""
write_status
prune_jobs
exit 0
