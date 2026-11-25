#!/bin/sh
# Point a Debian 12+ image at a configurable apt mirror, then install the given packages.
# Lists are space separated and tried in order; the first mirror that updates and installs wins.
set -eu

sources_file=${APT_DEBIAN_SOURCES_FILE:-/etc/apt/sources.list.d/debian.sources}
mirrors=${APT_DEBIAN_MIRRORS:-https://mirror.arvancloud.ir/debian https://deb.debian.org/debian}
security_mirrors=${APT_DEBIAN_SECURITY_MIRRORS:-}
ca_bundle=${APT_DEBIAN_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}

# Images such as pgvector/Postgres ship no ca-certificates, so HTTPS fails before it can install
# them. Debian's own sources are HTTP and apt still verifies package signatures.
mirror_for_image() {
    case "$1" in
        https://*)
            if [ ! -f "$ca_bundle" ]; then
                echo "No CA bundle at $ca_bundle; using HTTP for $1" >&2
                printf 'http://%s' "${1#https://}"
                return 0
            fi
            ;;
    esac
    printf '%s' "$1"
}

if [ ! -f "$sources_file" ]; then
    echo "Debian apt sources file not found: $sources_file. Set APT_DEBIAN_SOURCES_FILE to the image's deb822 source file." >&2
    exit 2
fi

original=$(mktemp)
trap 'rm -f "$original"' EXIT
cp "$sources_file" "$original"

remaining_security=$security_mirrors
for mirror in $mirrors; do
    security=
    if [ -n "$remaining_security" ]; then
        security=${remaining_security%% *}
        case "$remaining_security" in
            *" "*) remaining_security=${remaining_security#* } ;;
            *) remaining_security= ;;
        esac
    fi
    if [ -z "$security" ]; then
        base=${mirror%/}
        case "$base" in
            */debian) security="${base%debian}debian-security" ;;
            *) echo "No security mirror for $mirror. Set APT_DEBIAN_SECURITY_MIRRORS in .env (space-separated, same order as APT_DEBIAN_MIRRORS)." >&2; exit 2 ;;
        esac
    fi

    mirror=$(mirror_for_image "$mirror")
    security=$(mirror_for_image "$security")

    sed -E \
        -e "s#^(URIs:[[:space:]]*).*/debian-security/?\$#\1${security}#" \
        -e "s#^(URIs:[[:space:]]*).*/debian/?\$#\1${mirror}#" \
        "$original" > "$sources_file"

    rm -rf /var/lib/apt/lists/*
    if apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
        && { [ "$#" -eq 0 ] || apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends "$@"; }; then
        rm -rf /var/lib/apt/lists/*
        echo "Debian mirror in use: $mirror"
        exit 0
    fi
    echo "Debian mirror failed: $mirror" >&2
done

echo "All configured Debian mirrors failed. Set APT_DEBIAN_MIRRORS and APT_DEBIAN_SECURITY_MIRRORS in .env to reachable mirrors and rebuild." >&2
exit 1
