#!/bin/sh
# Builds asterisk-module-<version>.zip (root directory recuploader/) from
# freepbx-module/, with the version read from freepbx-module/module.xml.
#
# The vendored engine binaries (7zip, ffmpeg, gsm) are gitignored, so they
# come from, in order:
#   1. $SEDA_SANJ_VENDOR_BIN - a directory laid out like engine/bin/, or
#      a release zip containing recuploader/engine/bin/
#   2. the newest existing asterisk-module-*.zip in the repository root
#   3. whatever is already present in freepbx-module/engine/bin/
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MODULE="$ROOT/freepbx-module"
VERSION=$(sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' "$MODULE/module.xml" | head -n 1)
case "$VERSION" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "ERROR: cannot read a version from $MODULE/module.xml" >&2; exit 1 ;;
esac
OUT="$ROOT/asterisk-module-$VERSION.zip"

# A release must carry its own notes: module.xml, changelog.md and README.md have to agree.
grep -q "^## $VERSION " "$MODULE/changelog.md" || { echo "ERROR: freepbx-module/changelog.md has no '## $VERSION' entry" >&2; exit 1; }
grep -q "Module $VERSION" "$MODULE/README.md" || { echo "ERROR: freepbx-module/README.md title does not mention $VERSION" >&2; exit 1; }

# Never ship a release that fails its tests (PHP 7.4 = FreePBX 16, 8.2 = FreePBX 17).
if [ "${SEDA_SANJ_SKIP_TESTS:-0}" != 1 ]; then
  "$ROOT/scripts/test-freepbx-module.sh" 7.4 8.2 || { echo "ERROR: module tests failed; fix them or set SEDA_SANJ_SKIP_TESTS=1 knowingly" >&2; exit 1; }
fi

# A release is signed by the API when it is uploaded, which replaces this file with the real
# public key; the build only ships whatever is checked in. Warn when that file carries no usable
# Ed25519 key (the REPLACE_WITH_ sentinel, or a malformed line), because every server running
# this build then refuses automatic updates.
if ! PYTHONPATH= python3 - "$MODULE/assets/release-signing.pub" <<'PY'
import base64, sys
try:
    lines = [l.strip() for l in open(sys.argv[1], encoding='utf-8') if l.strip() and l.strip()[0] != '#']
    keys = [base64.b64decode(l, validate=True) for l in lines]
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if 1 <= len(keys) <= 3 and all(len(k) == 32 for k in keys) else 1)
PY
then
  echo "WARNING: assets/release-signing.pub has no valid Ed25519 public key - automatic updates" >&2
  echo "         will be disabled on servers running this build (see README.md)." >&2
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/sedasanj-build.XXXXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

cp -RL "$MODULE" "$WORK/recuploader"

VENDOR_PATTERNS="recuploader/engine/bin/7zip/7zzs-* recuploader/engine/bin/ffmpeg/ffmpeg-* recuploader/engine/bin/gsm/gsm-encode-x86_64 recuploader/engine/bin/gsm/gsm-encode-aarch64"
extract_vendor_zip() {
  mkdir -p "$WORK/vendor"
  # gsm-encode-aarch64 is absent from some older releases; unzip exits 11
  # when a pattern matches nothing, which is fine here.
  # shellcheck disable=SC2086
  unzip -oq "$1" $VENDOR_PATTERNS -d "$WORK/vendor" || [ $? -eq 11 ]
  cp -R "$WORK/vendor/recuploader/engine/bin/." "$WORK/recuploader/engine/bin/"
  echo "Vendored binaries taken from $1"
}

VENDOR="${SEDA_SANJ_VENDOR_BIN:-}"
if [ -n "$VENDOR" ]; then
  if [ -d "$VENDOR" ]; then
    cp -R "$VENDOR/." "$WORK/recuploader/engine/bin/"
    echo "Vendored binaries taken from $VENDOR"
  elif [ -f "$VENDOR" ]; then
    extract_vendor_zip "$VENDOR"
  else
    echo "ERROR: SEDA_SANJ_VENDOR_BIN=$VENDOR does not exist" >&2
    exit 1
  fi
else
  LATEST=$(ls "$ROOT"/asterisk-module-*.zip 2>/dev/null | sed 's:.*/asterisk-module-\(.*\)\.zip$:\1:' | sort -t . -k1,1n -k2,2n -k3,3n | tail -n 1)
  if [ -n "$LATEST" ]; then
    extract_vendor_zip "$ROOT/asterisk-module-$LATEST.zip"
  fi
fi

for required in 7zip/7zzs-x86_64 7zip/7zzs-aarch64 ffmpeg/ffmpeg-x86_64 ffmpeg/ffmpeg-aarch64 gsm/gsm-encode-x86_64; do
  if [ ! -f "$WORK/recuploader/engine/bin/$required" ]; then
    echo "ERROR: vendored binary engine/bin/$required is missing; set SEDA_SANJ_VENDOR_BIN" >&2
    exit 1
  fi
done
# Tests and VCS files are not needed on a PBX.
rm -rf "$WORK/recuploader/tests" "$WORK/recuploader/.gitignore"
chmod 755 "$WORK/recuploader/bin/sedasanj-recuploader-update.sh" "$WORK/recuploader"/*.sh

rm -f "$OUT"
(cd "$WORK" && zip -qr "$OUT" recuploader -x '*.DS_Store')
unzip -t "$OUT" >/dev/null
echo "Built $OUT"
