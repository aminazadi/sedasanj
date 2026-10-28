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

if grep -q '^REPLACE_WITH_' "$MODULE/assets/release-signing.pub"; then
  echo "WARNING: assets/release-signing.pub is still the placeholder - automatic updates" >&2
  echo "         will be disabled on servers running this build (see README.md)." >&2
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

cp -R "$MODULE" "$WORK/recuploader"

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
chmod 755 "$WORK/recuploader/bin/sedasanj-recuploader-update.sh" "$WORK/recuploader"/*.sh

rm -f "$OUT"
(cd "$WORK" && zip -qr "$OUT" recuploader -x '*.DS_Store')
unzip -t "$OUT" >/dev/null
echo "Built $OUT"
