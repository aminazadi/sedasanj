#!/bin/sh
set -eu

python=$1
shift

for index in "${PIP_INDEX_URL}" ${PIP_FALLBACK_INDEX_URLS:-}; do
    case "$index" in
        https://*) ;;
        *) echo "Unsupported PyPI index: $index" >&2; exit 2 ;;
    esac

    if PIP_INDEX_URL="$index" "$python" -m pip install "$@"; then
        exit 0
    fi
    echo "PyPI index failed: $index" >&2
done

echo 'All configured PyPI indexes failed' >&2
exit 1
