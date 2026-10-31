#!/bin/bash
set -euo pipefail
SOURCE=$(cd -- "$(dirname -- "$0")" && pwd)
exec "$SOURCE/activate.sh" "${1:-/usr/bin/php}"
