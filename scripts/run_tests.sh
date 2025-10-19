#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")"/.. >/dev/null 2>&1
  pwd
)"
cd "$ROOT_DIR"

MODE="${1:-fast}"
shift || true

PYTEST_BIN="${PYTEST_BIN:-$ROOT_DIR/.venv/bin/pytest}"
if [[ ! -x "$PYTEST_BIN" ]]; then
  echo "pytest 実行ファイルが見つかりません: $PYTEST_BIN" >&2
  exit 1
fi

case "$MODE" in
  fast)
    exec env PYTHONPATH="$ROOT_DIR" "$PYTEST_BIN" -m "not slow" "$@"
    ;;
  slow)
    exec env PYTHONPATH="$ROOT_DIR" "$PYTEST_BIN" -m slow "$@"
    ;;
  all)
    exec env PYTHONPATH="$ROOT_DIR" "$PYTEST_BIN" "$@"
    ;;
  *)
    echo "Usage: $0 [fast|slow|all] [extra pytest args...]" >&2
    exit 2
    ;;
esac
