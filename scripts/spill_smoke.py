#!/usr/bin/env python3
"""
Spill分布スモークチェック

目的:
- plan_final.json の weekly_summary を読み、pre/at/post 各ゾーンの spill_in/spill_out 合計を表示。
- anchor_policy ごとの直感的な分布を人力検証しやすくする（DET_near/AGG_far/blend）。

使い方:
  PYTHONPATH=. python3 scripts/spill_smoke.py -i out/plan_final.json
"""
from __future__ import annotations

import argparse
import json
from typing import Dict


def main() -> None:
    ap = argparse.ArgumentParser(description="Spill分布スモークチェック")
    ap.add_argument("-i", "--input", required=True, help="plan_final.json")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        plan = json.load(f)
    ws = list(plan.get("weekly_summary") or [])
    if not ws:
        print("no weekly_summary")
        return
    # 集計
    agg: Dict[str, Dict[str, float]] = {"pre": {}, "at": {}, "post": {}}
    for r in ws:
        z = str(r.get("zone") or "").lower()
        if z not in agg:
            continue
        d = agg[z]
        for k in (
            "spill_in",
            "spill_out",
            "capacity",
            "original_load",
            "adjusted_load",
        ):
            try:
                d[k] = d.get(k, 0.0) + float(r.get(k, 0) or 0)
            except Exception:
                pass
    cut = plan.get("boundary_summary") or {}
    print("policy=", (plan.get("reconcile_params") or {}).get("anchor_policy"))
    print("boundary=", cut)
    print("-- sums (by zone) --")
    for z in ("pre", "at", "post"):
        d = agg.get(z) or {}
        print(z, d)


if __name__ == "__main__":
    main()
