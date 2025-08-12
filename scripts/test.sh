#!/usr/bin/env bash
set -euo pipefail

PY=${PYTHON:-python3}

echo "Running unit tests..."
$PY -m unittest discover -s tests -p "test_*.py" -v

