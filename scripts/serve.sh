#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv"
PYTHON="python3"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[setup] creating $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Install deps if uvicorn is missing
if ! command -v uvicorn >/dev/null 2>&1; then
  echo "[setup] installing dependencies from requirements.txt"
  pip install -r requirements.txt
fi

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
RELOAD_FLAG=""
if [[ "${RELOAD:-0}" == "1" ]]; then
  RELOAD_FLAG="--reload --reload-dir ."
fi

echo "[run] starting uvicorn on http://$HOST:$PORT ${RELOAD_FLAG:+(reload)}"
nohup uvicorn main:app --host "$HOST" --port "$PORT" --loop asyncio $RELOAD_FLAG > uvicorn.out 2>&1 &
echo $! > uvicorn.pid
echo "[ok] pid $(cat uvicorn.pid)"
echo "[log] tail -f uvicorn.out"
