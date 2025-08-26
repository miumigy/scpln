#!/usr/bin/env bash
set -euo pipefail

# 粗密計画パイプライン一括実行（PR7）
# 例:
#   bash scripts/run_planning_pipeline.sh -I samples/planning -o out \
#     --weeks 4 --round int --lt-unit day

INPUT_DIR="samples/planning"
OUT_DIR="out"
WEEKS=4
ROUND_MODE="int"
LT_UNIT="day"  # day|week
WEEK_DAYS=7

while [[ $# -gt 0 ]]; do
  case "$1" in
    -I|--input-dir) INPUT_DIR="$2"; shift 2;;
    -o|--out) OUT_DIR="$2"; shift 2;;
    --weeks) WEEKS="$2"; shift 2;;
    --round) ROUND_MODE="$2"; shift 2;;
    --lt-unit) LT_UNIT="$2"; shift 2;;
    --week-days) WEEK_DAYS="$2"; shift 2;;
    *) echo "[warn] unknown arg: $1"; shift;;
  esac
done

mkdir -p "$OUT_DIR"

echo "[1/5] aggregate (family×period)"
PYTHONPATH=. python3 scripts/plan_aggregate.py -i "$INPUT_DIR" -o "$OUT_DIR/aggregate.json"

echo "[2/5] allocate (family→SKU, month→week)"
PYTHONPATH=. python3 scripts/allocate.py -i "$OUT_DIR/aggregate.json" -I "$INPUT_DIR" \
  -o "$OUT_DIR/sku_week.json" --weeks "$WEEKS" --round "$ROUND_MODE"

echo "[3/5] mrp (LT/lot/MOQ/BOM)"
PYTHONPATH=. python3 scripts/mrp.py -i "$OUT_DIR/sku_week.json" -I "$INPUT_DIR" \
  -o "$OUT_DIR/mrp.json" --lt-unit "$LT_UNIT" --weeks "$WEEKS" --week-days "$WEEK_DAYS"

echo "[4/5] reconcile (CRPライト)"
PYTHONPATH=. python3 scripts/reconcile.py -i "$OUT_DIR/sku_week.json" "$OUT_DIR/mrp.json" -I "$INPUT_DIR" \
  -o "$OUT_DIR/plan_final.json" --weeks "$WEEKS"

echo "[5/5] report (KPI)"
PYTHONPATH=. python3 scripts/report.py -i "$OUT_DIR/plan_final.json" -I "$INPUT_DIR" \
  -o "$OUT_DIR/report.csv"

echo "[ok] pipeline completed. outputs in $OUT_DIR"

