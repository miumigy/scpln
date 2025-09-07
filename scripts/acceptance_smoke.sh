#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${1:-http://localhost:8000}"
python3 "$(dirname "$0")/acceptance_smoke.py" --base-url "$BASE_URL"
