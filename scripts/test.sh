#!/usr/bin/env bash
set -euo pipefail

PY=.venv/bin/python

echo "Running unit tests..."
AUTH_MODE=none $PY -m unittest discover -s tests -p "test_*.py" -v

