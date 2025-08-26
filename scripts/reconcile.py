#!/usr/bin/env python3
"""
製販物整合（PR1スタブ）: 販売計画/生産計画/在庫/能力の整合ループの枠のみ。

使い方:
  python scripts/reconcile.py -i out/sku_week.json out/mrp.json -o out/plan_final.json
"""
from __future__ import annotations

import argparse
import json
import os


def main() -> None:
    ap = argparse.ArgumentParser(description="製販物整合 スタブ")
    ap.add_argument("-i", "--inputs", nargs="+", required=True, help="allocate, mrp の出力JSONを指定（複数）")
    ap.add_argument("-o", "--output", required=True, help="整合後の計画JSON（雛形）")
    args = ap.parse_args()

    summaries = []
    for p in args.inputs:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
            summaries.append({"path": p, "rows": len(d.get("rows", []))})

    payload = {
        "schema_version": "agg-1.0",
        "note": "PR1スタブ: 整合ロジックはPR5-6で実装予定",
        "inputs_summary": summaries,
        "rows": [],
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()

