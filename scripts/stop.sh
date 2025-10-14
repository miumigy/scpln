#!/usr/bin/env bash
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SERVICE="${1:-all}"

stop_process() {
  local name="$1"
  local pid_file="$2"
  local port="$3"

  echo "[info] stopping $name ..."

  if [[ -f "$pid_file" ]]; then
    PID=$(cat "$pid_file")
    if ps -p "$PID" > /dev/null 2>&1; then
      echo "[stop] killing $name pid $PID"
      kill "$PID" || true
    else
      echo "[info] pid file for $name exists but process $PID not running"
    fi
    rm -f "$pid_file"
  else
    echo "[info] $pid_file not found."
  fi

  # ポートでのフォールバック停止
  LISTEN_PIDS=$(ss -ltnp 2>/dev/null | awk -v p=":${port} " '$4 ~ p {print $NF}' | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)
  if [[ -n "$LISTEN_PIDS" ]]; then
    echo "[stop] killing listeners on :$port -> $LISTEN_PIDS"
    for p in $LISTEN_PIDS; do
      kill "$p" || true
    done
  fi
}

if [[ "$SERVICE" == "api" || "$SERVICE" == "all" ]]; then
  stop_process "uvicorn" "uvicorn.pid" "${PORT:-8000}"
fi

if [[ "$SERVICE" == "db" || "$SERVICE" == "datasette" || "$SERVICE" == "all" ]]; then
  stop_process "datasette" "datasette.pid" "${DB_PORT:-8001}"
fi

echo "[ok] 停止処理を完了しました"
