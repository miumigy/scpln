#!/usr/bin/env python3
"""
KPI/レポート出力（PR1スタブ）: 入力JSONから簡易CSVを出す枠だけ用意。

使い方:
  python scripts/report.py -i out/plan_final.json -o out/report.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os


def main() -> None:
    ap = argparse.ArgumentParser(description="レポート出力 スタブ")
    ap.add_argument("-i", "--input", required=True, help="reconcileの出力JSON")
    ap.add_argument("-o", "--output", required=True, help="CSV出力パス")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        plan = json.load(f)
    rows = plan.get("rows", [])

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # スタブ: ヘッダのみ
        w.writerow(["period", "family", "demand", "supply", "backlog"])  # 将来拡張前提
        for _r in rows:
            pass
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()

