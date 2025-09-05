#!/usr/bin/env python3
from __future__ import annotations

"""
carryoverログCSVエクスポート

入力: sku_week_adjusted.json（anchor_adjust出力）
出力: carryover.csv
"""

import argparse
import csv
import json
from typing import Any, Dict


def main() -> None:
    ap = argparse.ArgumentParser(description="carryoverログCSVエクスポート")
    ap.add_argument("-i", dest="input", required=True, help="sku_week_adjusted.json")
    ap.add_argument("-o", dest="output", required=True, help="CSV出力")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)
    rows = data.get("carryover") or []

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["family", "from_period", "to_period", "delta_demand", "delta_supply", "delta_backlog"],
        )
        w.writeheader()
        for r in rows:
            m = r.get("metrics") or {}
            w.writerow(
                {
                    "family": r.get("family"),
                    "from_period": r.get("from_period"),
                    "to_period": r.get("to_period"),
                    "delta_demand": m.get("demand"),
                    "delta_supply": m.get("supply"),
                    "delta_backlog": m.get("backlog"),
                }
            )
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()

