#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PORT="${PORT:-8000}"

echo "[status] repo: $ROOT_DIR"

if [[ -f uvicorn.pid ]]; then
  PID=$(cat uvicorn.pid)
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "[status] uvicorn pid=$PID is running"
    ps -p "$PID" -o pid,etime,cmd
  else
    echo "[status] uvicorn pid file exists but process not running (pid=$PID)"
  fi
else
  echo "[status] uvicorn.pid not found"
fi

echo "[status] listening sockets for :$PORT"
ss -ltnp 2>/dev/null | grep -E ":${PORT} " || echo "(no listener detected or permission denied)"

echo "[status] health check (/healthz)"
HOST=127.0.0.1 PORT="$PORT" bash scripts/health.sh || echo "(health check failed or blocked)"

echo "[status] recent logs (uvicorn.out)"
tail -n 20 uvicorn.out 2>/dev/null || echo "(no uvicorn.out yet)"

