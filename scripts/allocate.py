#!/usr/bin/env python3
"""
按分エンジン（PR1スタブ）: 入力/出力I/Fを確立し、実装は後続PRで追加。

使い方:
  python scripts/allocate.py -i out/aggregate.json -o out/sku_week.json
"""
from __future__ import annotations

import argparse
import json
import os


def main() -> None:
    ap = argparse.ArgumentParser(description="按分スタブ（ファミリ→SKU、月→週/日）")
    ap.add_argument("-i", "--input", required=True, help="plan_aggregateの出力JSON")
    ap.add_argument("-o", "--output", required=True, help="出力JSON（SKU×週の雛形）")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        agg = json.load(f)
    # スタブ: メタのみ継承
    payload = {
        "schema_version": agg.get("schema_version", "agg-1.0"),
        "note": "PR1スタブ: 按分ロジックはPR3で実装予定",
        "inputs_summary": agg.get("inputs_summary", {}),
        "rows": [],
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()

