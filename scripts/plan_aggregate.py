#!/usr/bin/env python3
"""
粗粒度S&OP（ファミリ×月次）入力のバリデーションと雛形出力を行うCLIスタブ。

PR1の目的: スキーマ/I-F/サンプルの土台を整える（ロジックは後続PR）。

使い方:
  python scripts/plan_aggregate.py -i samples/planning -o out/aggregate.json
  python scripts/plan_aggregate.py --demand samples/planning/demand_family.csv \
      --capacity samples/planning/capacity.csv --mix samples/planning/mix_share.csv -o out/aggregate.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from typing import Dict, Any, List
# 注意: PR1 のスタブは外部依存を避けるため、pydantic等の導入は行わない
# 将来PRで planning.schemas を参照し厳格化する


def _read_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _coerce_float(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    v = row.get(key)
    try:
        return float(v)
    except Exception:
        return default


def load_inputs(
    base_dir: str | None,
    demand_file: str | None,
    capacity_file: str | None,
    mix_file: str | None,
) -> Dict[str, Any]:
    def p(rel: str | None) -> str | None:
        if rel is None:
            return None
        if base_dir is None:
            return rel
        return os.path.join(base_dir, rel)

    demand_rows: List[Dict[str, Any]] = []
    capacity_rows: List[Dict[str, Any]] = []
    mix_rows: List[Dict[str, Any]] = []

    if demand_file or base_dir:
        demand_rows = _read_csv(p(demand_file or "demand_family.csv"))
    if capacity_file or base_dir:
        capacity_rows = _read_csv(p(capacity_file or "capacity.csv"))
    if mix_file or base_dir:
        mix_rows = _read_csv(p(mix_file or "mix_share.csv"))

    # 形式チェック（軽量）
    _ = [
        (r["family"], r["period"], _coerce_float(r, "demand"))
        for r in demand_rows
        if r.get("family") and r.get("period")
    ]
    _ = [
        (r["workcenter"], r["period"], _coerce_float(r, "capacity"))
        for r in capacity_rows
        if r.get("workcenter") and r.get("period")
    ]
    _ = [
        (r["family"], r["sku"], _coerce_float(r, "share"))
        for r in mix_rows
        if r.get("family") and r.get("sku")
    ]

    return {
        "demand_rows": demand_rows,
        "capacity_rows": capacity_rows,
        "mix_rows": mix_rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="粗粒度S&OP入力の検証と雛形出力（PR1スタブ）")
    ap.add_argument("-i", "--input-dir", dest="input_dir", default=None, help="CSVフォルダ（demand_family.csv/capacity.csv/mix_share.csv）")
    ap.add_argument("--demand", dest="demand", default=None, help="demand_family.csv")
    ap.add_argument("--capacity", dest="capacity", default=None, help="capacity.csv")
    ap.add_argument("--mix", dest="mix", default=None, help="mix_share.csv")
    ap.add_argument("-o", "--output", dest="output", required=True, help="出力JSONパス（雛形）")
    args = ap.parse_args()

    ds = load_inputs(args.input_dir, args.demand, args.capacity, args.mix)

    payload = {
        "schema_version": "agg-1.0",
        "note": (
            "PR1スタブ: 入力の整合性を確認し、次段の最適化/ヒューリスティク実装に備えた空の計画を出力。"
        ),
        "inputs_summary": {
            "demand_rows": len(ds["demand_rows"]),
            "capacity_rows": len(ds["capacity_rows"]),
            "mix_rows": len(ds["mix_rows"]),
        },
        "rows": [],
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()
