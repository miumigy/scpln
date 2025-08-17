#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="uvicorn.pid"

if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "[stop] killing pid $PID"
    kill "$PID" || true
  else
    echo "[info] pid file exists but process $PID not running"
  fi
  rm -f "$PID_FILE"
else
  echo "[warn] uvicorn.pid が見つかりません。明示停止を試みます。"
fi

# ポートで待ち受け中の uvicorn があれば停止（フォールバック）
PORT="${PORT:-8000}"
LISTEN_PIDS=$(ss -ltnp 2>/dev/null | awk -v p=":${PORT} " '$4 ~ p {print $NF}' | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)
if [[ -n "$LISTEN_PIDS" ]]; then
  echo "[stop] killing listeners on :$PORT -> $LISTEN_PIDS"
  for p in $LISTEN_PIDS; do
    kill "$p" || true
  done
fi

echo "[ok] 停止処理を完了しました"
