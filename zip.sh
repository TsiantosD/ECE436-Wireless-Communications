#!/usr/bin/env bash
set -euo pipefail

# Create the submission archive from the repository root.
# Includes everything except Git metadata and the generated archive itself.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ZIP_NAME="nikas_mpalamotis_tsiantos.zip"

# Remove a previous archive so re-running this script cannot include it.
rm -f "$ZIP_NAME"

if command -v zip >/dev/null 2>&1; then
    zip -r "$ZIP_NAME" . \
        -x './.git/*' \
        -x '.git/*' \
        -x "./$ZIP_NAME" \
        -x "$ZIP_NAME"
elif command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

root = Path('.').resolve()
zip_name = 'nikas_mpalamotis_tsiantos.zip'
zip_path = root / zip_name

with ZipFile(zip_path, 'w', ZIP_DEFLATED) as zf:
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        rel_posix = rel.as_posix()

        if rel.parts and rel.parts[0] == '.git':
            continue
        if rel_posix == zip_name:
            continue
        if path.is_dir():
            continue

        info = ZipInfo.from_file(path, rel_posix)
        with path.open('rb') as f:
            zf.writestr(info, f.read(), compress_type=ZIP_DEFLATED)
PY
else
    echo "Error: neither 'zip' nor 'python3' is installed." >&2
    exit 1
fi

echo "Created $ZIP_NAME"
