#!/usr/bin/env bash
set -euo pipefail

DB_PATH=${SCPLN_DB:-data/scpln.db}
OUT_DIR=${1:-backup}
mkdir -p "$OUT_DIR"
ts=$(date +%Y%m%d_%H%M%S)
if [ -f "$DB_PATH" ]; then
  cp -p "$DB_PATH" "$OUT_DIR/scpln_${ts}.db"
  echo "Backup created: $OUT_DIR/scpln_${ts}.db"
else
  echo "DB not found: $DB_PATH" >&2
  exit 1
fi

