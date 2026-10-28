#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

cp -R "$ROOT/freepbx-module" "$WORK/recuploader"
mkdir -p "$WORK/vendor"
unzip -oq "$ROOT/asterisk-module-1.1.8.zip" \
  'recuploader/engine/bin/7zip/7zzs-*' \
  'recuploader/engine/bin/ffmpeg/ffmpeg-*' \
  'recuploader/engine/bin/gsm/gsm-encode-x86_64' \
  -d "$WORK/vendor"
cp -R "$WORK/vendor/recuploader/engine/bin/." "$WORK/recuploader/engine/bin/"
rm -f "$ROOT/asterisk-module-1.2.1.zip"
(cd "$WORK" && zip -qr "$ROOT/asterisk-module-1.2.1.zip" recuploader)
unzip -t "$ROOT/asterisk-module-1.2.1.zip" >/dev/null
