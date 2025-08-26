#!/usr/bin/env python3
"""
製販物整合（PR5, CRPライト）: 計画解放（planned_order_release）を週次能力に合わせて調整。

機能（v0）
- 入力: allocate（SKU×週）と mrp（item×週）を受け取り、FG（mix_shareにあるSKU）を能力制約で調整
- 能力: capacity.csv（月次, workcenter）を週等分して適用（単一WCを総量として扱うv0）
- 調整: 週順に処理し、前週の余剰能力を繰越して前倒し、超過分は次週へ繰越（スピル）
- 出力: mrp行に `planned_order_release_adj` を付与。週別サマリ（load/capacity/adjusted/spill）を付加

使い方:
  python scripts/reconcile.py -i out/sku_week.json out/mrp.json -I samples/planning -o out/plan_final.json --weeks 4
"""
from __future__ import annotations

import argparse
import json
import os
import csv
from typing import Dict, Any, List, Tuple, DefaultDict


def _read_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_mix(input_dir: str | None, mix_path: str | None) -> List[str]:
    path = mix_path or (os.path.join(input_dir, "mix_share.csv") if input_dir else None)
    skus: List[str] = []
    if path and os.path.exists(path):
        rows = _read_csv(path)
        for r in rows:
            sku = str(r.get("sku"))
            if sku and sku not in skus:
                skus.append(sku)
    return skus


def _weeks_from(alloc: Dict[str, Any], mrp: Dict[str, Any]) -> List[str]:
    seen = []
    for rec in alloc.get("rows", []):
        w = str(rec.get("week"))
        if w and w not in seen:
            seen.append(w)
    for rec in mrp.get("rows", []):
        w = str(rec.get("week"))
        if w and w not in seen:
            seen.append(w)
    return sorted(seen)


def _weekly_capacity(input_dir: str | None, capacity_path: str | None, *, weeks_per_period: int, weeks: List[str]) -> Dict[str, float]:
    path = capacity_path or (os.path.join(input_dir, "capacity.csv") if input_dir else None)
    cap_by_period: DefaultDict[str, float] = __import__("collections").defaultdict(float)
    if path and os.path.exists(path):
        for r in _read_csv(path):
            per = str(r.get("period"))
            try:
                c = float(r.get("capacity", 0) or 0)
            except Exception:
                c = 0.0
            cap_by_period[per] += c  # 複数WCは合算
    # 週へ展開（等分）
    out: Dict[str, float] = {}
    for w in weeks:
        # 期待形式 'YYYY-MM-Wk' → 'YYYY-MM'
        per = w[:7] if len(w) >= 7 and w[4] == '-' else w
        monthly = cap_by_period.get(per, 0.0)
        out[w] = monthly / max(1, weeks_per_period)
    return out


def _adjust_by_capacity(weeks: List[str], load_by_week: Dict[str, float], cap_by_week: Dict[str, float]) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    adj: Dict[str, float] = {}
    report: List[Dict[str, Any]] = []
    slack_carry = 0.0
    spill_next = 0.0
    for w in weeks:
        cap = float(cap_by_week.get(w, 0.0))
        demand = float(load_by_week.get(w, 0.0)) + spill_next
        effective = cap + slack_carry
        if demand <= effective:
            adj[w] = demand
            slack_carry = effective - demand
            spill_made = 0.0
        else:
            adj[w] = effective
            spill_made = demand - effective
            slack_carry = 0.0
        spill_next = spill_made
        report.append({
            "week": w,
            "capacity": cap,
            "original_load": float(load_by_week.get(w, 0.0)),
            "carried_slack_in": round(effective - cap, 6),
            "spill_in": round(demand - float(load_by_week.get(w, 0.0)), 6),
            "adjusted_load": adj[w],
            "spill_out": spill_made,
            "slack_carry_out": slack_carry,
        })
    return adj, report


def main() -> None:
    ap = argparse.ArgumentParser(description="製販物整合（CRPライト）")
    ap.add_argument("-i", "--inputs", nargs=2, required=True, help="allocate.json と mrp.json のパス（順不同可）")
    ap.add_argument("-o", "--output", required=True, help="整合後の計画JSON")
    ap.add_argument("-I", "--input-dir", dest="input_dir", default=None, help="CSVフォルダ（capacity.csv, mix_share.csv）")
    ap.add_argument("--capacity", dest="capacity", default=None, help="capacity.csv")
    ap.add_argument("--mix", dest="mix", default=None, help="mix_share.csv（FG判定）")
    ap.add_argument("--weeks", dest="weeks_per_period", type=int, default=4, help="1期間の週数")
    args = ap.parse_args()

    # 入力を識別
    with open(args.inputs[0], encoding="utf-8") as f:
        a0 = json.load(f)
    with open(args.inputs[1], encoding="utf-8") as f:
        a1 = json.load(f)
    if "sku" in json.dumps(a0.get("rows", [])[:1]):
        alloc, mrp = a0, a1
    else:
        alloc, mrp = a1, a0

    weeks = _weeks_from(alloc, mrp)
    fg_skus = set(_load_mix(args.input_dir, args.mix))
    cap_w = _weekly_capacity(args.input_dir, args.capacity, weeks_per_period=args.weeks_per_period, weeks=weeks)

    # 週別のFG解放ロード
    load_by_week: DefaultDict[str, float] = __import__("collections").defaultdict(float)
    for r in mrp.get("rows", []):
        it = str(r.get("item"))
        if it not in fg_skus:
            continue
        w = str(r.get("week"))
        por = float(r.get("planned_order_release", 0) or 0)
        load_by_week[w] += por

    adj_by_week, week_report = _adjust_by_capacity(weeks, load_by_week, cap_w)

    # 週別係数を用いてFGの解放をスケーリング
    rows_out: List[Dict[str, Any]] = []
    for r in mrp.get("rows", []):
        it = str(r.get("item"))
        w = str(r.get("week"))
        por = float(r.get("planned_order_release", 0) or 0)
        if it in fg_skus:
            base = load_by_week.get(w, 0.0)
            target = adj_by_week.get(w, base)
            factor = (target / base) if base > 0 else 1.0
            adj_rel = por * factor
        else:
            adj_rel = por
        r2 = dict(r)
        r2["planned_order_release_adj"] = round(adj_rel, 6)
        rows_out.append(r2)

    payload = {
        "schema_version": mrp.get("schema_version", "agg-1.0"),
        "note": "PR5: CRPライト（週次能力に合わせて解放を前倒し/繰越で調整）",
        "inputs_summary": {
            "allocate_rows": len(alloc.get("rows", [])),
            "mrp_rows": len(mrp.get("rows", [])),
            "weeks": len(weeks),
            "fg_skus": len(fg_skus),
        },
        "weekly_summary": week_report,
        "rows": rows_out,
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()
