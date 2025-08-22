#!/usr/bin/env bash
set -euo pipefail

SRC=${1:-}
DB_PATH=${SCPLN_DB:-data/scpln.db}
if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
  echo "Usage: $0 <backup_db_path>" >&2
  exit 1
fi
mkdir -p "$(dirname "$DB_PATH")"
cp -p "$SRC" "$DB_PATH"
echo "Restored $SRC -> $DB_PATH"

