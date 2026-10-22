#!/bin/sh
set -eu

mirrors=${APT_UBUNTU_MIRRORS:-https://mirror.arvancloud.ir/ubuntu/ https://mirrors.ustc.edu.cn/ubuntu/ https://mirrors.tuna.tsinghua.edu.cn/ubuntu/}
sources_file=$(mktemp)
trap 'rm -f "$sources_file"' EXIT

for mirror in $mirrors; do
    mirror=${mirror%/}/
    case "$mirror" in
        http://*|https://*) ;;
        *) echo "Unsupported Ubuntu mirror: $mirror" >&2; exit 2 ;;
    esac

    : > "$sources_file"
    for suite in jammy jammy-updates jammy-security jammy-backports; do
        printf 'deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] %s %s main restricted universe multiverse\n' "$mirror" "$suite" >> "$sources_file"
    done
    rm -rf /var/lib/apt/lists/*
    if apt-get -o Dir::Etc::sourcelist="$sources_file" -o Dir::Etc::sourceparts=- \
            -o Acquire::Retries=1 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update \
        && apt-get -o Dir::Etc::sourcelist="$sources_file" -o Dir::Etc::sourceparts=- \
            -o Acquire::Retries=1 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 \
            install -y --no-install-recommends \
            ffmpeg curl libgomp1 build-essential cmake ninja-build; then
        rm -rf /var/lib/apt/lists/*
        exit 0
    fi
    echo "Ubuntu mirror failed: $mirror" >&2
done

echo 'All configured Ubuntu mirrors failed' >&2
exit 1
