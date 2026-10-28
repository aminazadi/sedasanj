#!/usr/bin/env bash
# Builds bin/gsm/gsm-encode-<arch> for the architecture this script is
# run on (uname -m), statically linked against libgsm so the resulting
# binary has no runtime dependency once built. Matches the vendoring
# convention already used for bin/7zip/7zzs-<arch> and
# bin/ffmpeg/ffmpeg-<arch> in this repo.
#
# Run this once per architecture you need to support (typically
# x86_64; run it again on an aarch64 box, or under an aarch64 chroot/
# cross-toolchain, if you also deploy on aarch64 Asterisk boxes).
set -euo pipefail

cd "$(dirname "$0")"

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) ARCH=x86_64 ;;
    aarch64|arm64) ARCH=aarch64 ;;
esac

if ! command -v gcc >/dev/null 2>&1; then
    echo "gcc not found - install build-essential (Debian/Ubuntu) or equivalent" >&2
    exit 1
fi

if [ ! -f /usr/include/gsm.h ] && [ ! -f /usr/include/gsm/gsm.h ]; then
    echo "libgsm headers not found - installing libgsm1-dev..." >&2
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y --no-install-recommends libgsm1-dev
    else
        echo "No apt-get available; install the libgsm development package for your distro manually" >&2
        exit 1
    fi
fi

OUT="gsm-encode-${ARCH}"
gcc -O2 -Wall -Wextra -static -o "$OUT" gsm-encode.c -lgsm
strip "$OUT"
chmod +x "$OUT"

echo "Built $(pwd)/$OUT"
file "$OUT" 2>/dev/null || true
