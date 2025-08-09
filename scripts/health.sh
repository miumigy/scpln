#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
URL="http://$HOST:$PORT/healthz"

python3 - "$URL" <<'PY'
import sys, urllib.request
url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=2) as r:
        data = r.read().decode('utf-8', 'ignore')
        print(data)
        sys.exit(0 if r.status == 200 else 1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
PY
