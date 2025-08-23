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

# Load .env if present (export all variables)
if [[ -f .env ]]; then
  echo "[env] loading .env"
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  echo "[env] AUTH_MODE=${AUTH_MODE:-none} JOBS_BACKEND=${JOBS_BACKEND:-memory} REGISTRY_BACKEND=${REGISTRY_BACKEND:-memory}"
fi

# Install deps if uvicorn is missing
# 依存インストール: uvicorn が無い、または requirements.txt が更新、または必須モジュール不足の場合に実行
REQ_HASH_FILE="$VENV_DIR/requirements.hash"
NEED_INSTALL=0

if ! command -v uvicorn >/dev/null 2>&1; then
  NEED_INSTALL=1
fi

if [[ -f requirements.txt ]]; then
  NEW_HASH=$(sha256sum requirements.txt | awk '{print $1}')
  OLD_HASH=$(cat "$REQ_HASH_FILE" 2>/dev/null || true)
  if [[ "$NEW_HASH" != "$OLD_HASH" ]]; then
    NEED_INSTALL=1
  fi
fi

# FastAPI UI で必要なモジュールの存在チェック（不足時はインストール）
python - <<'PY' 2>/dev/null || NEED_INSTALL=1
import importlib
for m in ("fastapi","jinja2","multipart"):
    importlib.import_module(m)
PY

if [[ "$NEED_INSTALL" == "1" ]]; then
  echo "[setup] installing dependencies from requirements.txt"
  pip install -r requirements.txt
  if [[ -f requirements.txt ]]; then
    sha256sum requirements.txt | awk '{print $1}' > "$REQ_HASH_FILE" || true
  fi
fi

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
RELOAD_FLAG=""
if [[ "${RELOAD:-0}" == "1" ]]; then
  RELOAD_FLAG="--reload --reload-dir ."
fi

# 既存の待ち受けがある場合は停止を試みる
if ss -ltnp 2>/dev/null | grep -q ":${PORT} "; then
  echo "[warn] :$PORT is already in use. attempting to stop existing uvicorn..."
  PORT="$PORT" bash scripts/stop.sh || true
  sleep 1
fi

echo "[run] starting uvicorn on http://$HOST:$PORT ${RELOAD_FLAG:+(reload)}"
nohup uvicorn main:app --host "$HOST" --port "$PORT" --loop asyncio $RELOAD_FLAG > uvicorn.out 2>&1 &
echo $! > uvicorn.pid
echo "[ok] pid $(cat uvicorn.pid)"
echo "[log] tail -f uvicorn.out"

# Optional: seed hierarchy if requested
if [[ "${SEED_HIERARCHY:-0}" == "1" ]]; then
  echo "[seed] seeding product/location hierarchy from configs/*.json"
  source "$VENV_DIR/bin/activate"
  python scripts/seed_hierarchy.py || true
fi
