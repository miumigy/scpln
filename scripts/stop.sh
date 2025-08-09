#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f uvicorn.pid ]]; then
  echo "[warn] uvicorn.pid が見つかりません。すでに停止している可能性があります。"
  exit 0
fi

PID=$(cat uvicorn.pid)
if ps -p "$PID" > /dev/null 2>&1; then
  echo "[stop] killing pid $PID"
  kill "$PID"
else
  echo "[info] プロセス $PID は稼働していません"
fi

rm -f uvicorn.pid
echo "[ok] 停止しました"

