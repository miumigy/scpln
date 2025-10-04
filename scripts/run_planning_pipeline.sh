#!/usr/bin/env bash
set -euo pipefail

# 互換用シェルエントリ。将来的には run_planning_pipeline.py を直接利用してください。

PYTHONPATH=. python3 scripts/run_planning_pipeline.py "$@"
