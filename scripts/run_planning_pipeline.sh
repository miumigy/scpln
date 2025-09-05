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
ANCHOR_POLICY=""
CUTOVER_DATE=""
RECON_WINDOW_DAYS=""
APPLY_ADJUST=0
CALENDAR_MODE="simple"
MAX_ADJUST_RATIO=""
CARRYOVER=""
TOL_ABS=""
TOL_REL=""
CARRYOVER_SPLIT=""
BLEND_SPLIT_NEXT=""
BLEND_WEIGHT_MODE=""
PRESET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -I|--input-dir) INPUT_DIR="$2"; shift 2;;
    -o|--out) OUT_DIR="$2"; shift 2;;
    --weeks) WEEKS="$2"; shift 2;;
    --round) ROUND_MODE="$2"; shift 2;;
    --lt-unit) LT_UNIT="$2"; shift 2;;
    --week-days) WEEK_DAYS="$2"; shift 2;;
    --anchor-policy) ANCHOR_POLICY="$2"; shift 2;;
    --cutover-date) CUTOVER_DATE="$2"; shift 2;;
    --recon-window-days) RECON_WINDOW_DAYS="$2"; shift 2;;
    --apply-adjusted) APPLY_ADJUST=1; shift 1;;
    --calendar-mode) CALENDAR_MODE="$2"; shift 2;;
    --max-adjust-ratio) MAX_ADJUST_RATIO="$2"; shift 2;;
    --carryover) CARRYOVER="$2"; shift 2;;
    --tol-abs) TOL_ABS="$2"; shift 2;;
    --tol-rel) TOL_REL="$2"; shift 2;;
    --carryover-split) CARRYOVER_SPLIT="$2"; shift 2;;
    --blend-split-next) BLEND_SPLIT_NEXT="$2"; shift 2;;
    --blend-weight-mode) BLEND_WEIGHT_MODE="$2"; shift 2;;
    --preset) PRESET="$2"; shift 2;;
    *) echo "[warn] unknown arg: $1"; shift;;
  esac
done

# プリセット適用（未指定の値に限り上書き）
case "$PRESET" in
  det_near)
    [[ -z "$ANCHOR_POLICY" ]] && ANCHOR_POLICY="DET_near"
    [[ -z "$RECON_WINDOW_DAYS" ]] && RECON_WINDOW_DAYS="7"
    ;;
  agg_far)
    [[ -z "$ANCHOR_POLICY" ]] && ANCHOR_POLICY="AGG_far"
    [[ -z "$RECON_WINDOW_DAYS" ]] && RECON_WINDOW_DAYS="7"
    ;;
  blend)
    [[ -z "$ANCHOR_POLICY" ]] && ANCHOR_POLICY="blend"
    [[ -z "$RECON_WINDOW_DAYS" ]] && RECON_WINDOW_DAYS="14"
    [[ -z "$BLEND_WEIGHT_MODE" ]] && BLEND_WEIGHT_MODE="tri"
    ;;
esac

mkdir -p "$OUT_DIR"

echo "[1/5] aggregate (family×period)"
PYTHONPATH=. python3 scripts/plan_aggregate.py -i "$INPUT_DIR" -o "$OUT_DIR/aggregate.json"

echo "[2/5] allocate (family→SKU, month→week)"
PYTHONPATH=. python3 scripts/allocate.py -i "$OUT_DIR/aggregate.json" -I "$INPUT_DIR" \
  -o "$OUT_DIR/sku_week.json" --weeks "$WEEKS" --round "$ROUND_MODE"

echo "[3/5] mrp (LT/lot/MOQ/BOM)"
PYTHONPATH=. python3 scripts/mrp.py -i "$OUT_DIR/sku_week.json" -I "$INPUT_DIR" \
  -o "$OUT_DIR/mrp.json" --lt-unit "$LT_UNIT" --weeks "$WEEKS" --week-days "$WEEK_DAYS"

echo "[4/6] reconcile (CRPライト)"
PYTHONPATH=. python3 scripts/reconcile.py -i "$OUT_DIR/sku_week.json" "$OUT_DIR/mrp.json" -I "$INPUT_DIR" \
  -o "$OUT_DIR/plan_final.json" --weeks "$WEEKS" \
  ${CUTOVER_DATE:+--cutover-date "$CUTOVER_DATE"} \
  ${RECON_WINDOW_DAYS:+--recon-window-days "$RECON_WINDOW_DAYS"} \
  ${ANCHOR_POLICY:+--anchor-policy "$ANCHOR_POLICY"} \
  ${BLEND_SPLIT_NEXT:+--blend-split-next "$BLEND_SPLIT_NEXT"} \
  ${BLEND_WEIGHT_MODE:+--blend-weight-mode "$BLEND_WEIGHT_MODE"}
echo "[5/6] reconcile-levels (AGG↔DET 差分ログ)"
PYTHONPATH=. python3 scripts/reconcile_levels.py -i "$OUT_DIR/aggregate.json" "$OUT_DIR/sku_week.json" \
  -o "$OUT_DIR/reconciliation_log.json" --version pipeline --tol-abs 1e-6 --tol-rel 1e-6 \
  ${CUTOVER_DATE:+--cutover-date "$CUTOVER_DATE"} ${ANCHOR_POLICY:+--anchor-policy "$ANCHOR_POLICY"}
PYTHONPATH=. python3 scripts/export_reconcile_csv.py -i "$OUT_DIR/reconciliation_log.json" \
  -o "$OUT_DIR/reconciliation_before.csv" --label before
PYTHONPATH=. python3 scripts/export_reconcile_csv.py -i "$OUT_DIR/reconciliation_log.json" \
  -o "$OUT_DIR/reconciliation_violations_before.csv" --label before --only-violations

# optional: anchor調整（v2最小、オフライン検証用）
if [[ -n "$ANCHOR_POLICY" && -n "$CUTOVER_DATE" ]]; then
  echo "[5b] anchor-adjust (DET_near)"
  PYTHONPATH=. python3 scripts/anchor_adjust.py -i "$OUT_DIR/aggregate.json" "$OUT_DIR/sku_week.json" \
    -o "$OUT_DIR/sku_week_adjusted.json" --cutover-date "$CUTOVER_DATE" --anchor-policy "$ANCHOR_POLICY" \
    ${RECON_WINDOW_DAYS:+--recon-window-days "$RECON_WINDOW_DAYS"} --weeks "$WEEKS" --calendar-mode "$CALENDAR_MODE" \
    ${MAX_ADJUST_RATIO:+--max-adjust-ratio "$MAX_ADJUST_RATIO"} ${CARRYOVER:+--carryover "$CARRYOVER"} \
    ${TOL_ABS:+--tol-abs "$TOL_ABS"} ${TOL_REL:+--tol-rel "$TOL_REL"} \
    ${CARRYOVER_SPLIT:+--carryover-split "$CARRYOVER_SPLIT"} -I "$INPUT_DIR"
  echo "[5c] reconcile-levels (after adjustment)"
  PYTHONPATH=. python3 scripts/reconcile_levels.py -i "$OUT_DIR/aggregate.json" "$OUT_DIR/sku_week_adjusted.json" \
    -o "$OUT_DIR/reconciliation_log_adjusted.json" --version pipeline-adjusted --tol-abs 1e-6 --tol-rel 1e-6 \
    ${CUTOVER_DATE:+--cutover-date "$CUTOVER_DATE"} ${ANCHOR_POLICY:+--anchor-policy "$ANCHOR_POLICY"}
  PYTHONPATH=. python3 scripts/export_reconcile_csv.py \
    -i "$OUT_DIR/reconciliation_log.json" --label before \
    -j "$OUT_DIR/reconciliation_log_adjusted.json" --label2 after \
    -o "$OUT_DIR/reconciliation_compare.csv"
  PYTHONPATH=. python3 scripts/export_reconcile_csv.py \
    -i "$OUT_DIR/reconciliation_log.json" --label before \
    -j "$OUT_DIR/reconciliation_log_adjusted.json" --label2 after \
    -o "$OUT_DIR/reconciliation_violations_compare.csv" --only-violations
  PYTHONPATH=. python3 scripts/export_carryover_csv.py -i "$OUT_DIR/sku_week_adjusted.json" -o "$OUT_DIR/carryover.csv"
  if [[ "$APPLY_ADJUST" -eq 1 ]]; then
    echo "[5d] mrp (adjusted)"
    PYTHONPATH=. python3 scripts/mrp.py -i "$OUT_DIR/sku_week_adjusted.json" -I "$INPUT_DIR" \
      -o "$OUT_DIR/mrp_adjusted.json" --lt-unit "$LT_UNIT" --weeks "$WEEKS" --week-days "$WEEK_DAYS"
    echo "[5e] reconcile (adjusted)"
    PYTHONPATH=. python3 scripts/reconcile.py -i "$OUT_DIR/sku_week_adjusted.json" "$OUT_DIR/mrp_adjusted.json" -I "$INPUT_DIR" \
      -o "$OUT_DIR/plan_final_adjusted.json" --weeks "$WEEKS" \
      ${CUTOVER_DATE:+--cutover-date "$CUTOVER_DATE"} \
      ${RECON_WINDOW_DAYS:+--recon-window-days "$RECON_WINDOW_DAYS"} \
      ${ANCHOR_POLICY:+--anchor-policy "$ANCHOR_POLICY"} \
      ${BLEND_SPLIT_NEXT:+--blend-split-next "$BLEND_SPLIT_NEXT"} \
      ${BLEND_WEIGHT_MODE:+--blend-weight-mode "$BLEND_WEIGHT_MODE"}
    echo "[5f] report (adjusted)"
    PYTHONPATH=. python3 scripts/report.py -i "$OUT_DIR/plan_final_adjusted.json" -I "$INPUT_DIR" \
      -o "$OUT_DIR/report_adjusted.csv"
  fi
fi

echo "[6/6] report (KPI)"
PYTHONPATH=. python3 scripts/report.py -i "$OUT_DIR/plan_final.json" -I "$INPUT_DIR" \
  -o "$OUT_DIR/report.csv"

echo "[ok] pipeline completed. outputs in $OUT_DIR"
