#!/usr/bin/env python3
"""
MRPライト（PR1スタブ）: 入力/出力I/Fのみ。

使い方:
  python scripts/mrp.py -i out/sku_week.json -o out/mrp.json
"""
from __future__ import annotations

import argparse
import json
import os


def main() -> None:
    ap = argparse.ArgumentParser(description="MRPライト スタブ")
    ap.add_argument("-i", "--input", required=True, help="allocateの出力JSON")
    ap.add_argument("-o", "--output", required=True, help="出力JSON（部材手配の雛形）")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        alloc = json.load(f)
    payload = {
        "schema_version": alloc.get("schema_version", "agg-1.0"),
        "note": "PR1スタブ: MRPロジックはPR4で実装予定",
        "inputs_summary": alloc.get("inputs_summary", {}),
        "rows": [],
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()

