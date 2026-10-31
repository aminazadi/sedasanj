#!/bin/bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' "$ROOT/issabel-module/module.xml" | head -n 1)
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
grep -q "^## $VERSION " "$ROOT/issabel-module/changelog.md"
grep -q "Module $VERSION" "$ROOT/issabel-module/README.md"
if [ "${SEDA_SANJ_SKIP_TESTS:-0}" != 1 ]; then
  "$ROOT/scripts/test-issabel-module.sh" 5.6 7.4 8.2
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp -RL "$ROOT/issabel-module" "$WORK/recuploader"
rm -rf "$WORK/recuploader/tests"
cp "$ROOT/freepbx-module/RIGHTS.md" "$WORK/recuploader/RIGHTS.md"
chmod 755 "$WORK/recuploader/"*.sh "$WORK/recuploader/bin/"*.php
python3 - "$WORK" "$ROOT/deliverables/recuploader-$VERSION.tgz" <<'PY'
import sys,tarfile
from pathlib import Path
source, output = map(Path, sys.argv[1:])
output.parent.mkdir(parents=True, exist_ok=True)
with tarfile.open(output, 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
    for path in sorted((source/'recuploader').rglob('*')):
        if '.DS_Store' in path.parts or '__pycache__' in path.parts:
            continue
        archive.add(path, arcname=str(path.relative_to(source)), recursive=False)
print(output)
PY
