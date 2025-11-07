#!/usr/bin/env python3
"""
粗粒度S&OP（ファミリ×月次）: 需要と能力から供給/残需要（バックログ）を算出する簡易ヒューリスティク。

PR2の範囲: periodごとの総需要に対し、能力が不足する場合は各familyへ比例配分で供給。
  - 入力: demand_family.csv, capacity.csv（複数workcenterはperiod合算）
  - 出力: rows: [{family, period, demand, supply, backlog, capacity_total}]

使い方:
  python scripts/plan_aggregate.py -i samples/planning -o out/aggregate.json --round int
  python scripts/plan_aggregate.py --demand samples/planning/demand_family.csv \
      --capacity samples/planning/capacity.csv --mix samples/planning/mix_share.csv -o out/aggregate.json
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, DefaultDict

from core.plan_repository import PlanRepositoryError
from scripts.plan_pipeline_io import (
    resolve_storage_config,
    store_aggregate_payload,
)
from scripts.rounding_utils import round_quantity, distribute_int

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


def _finalize_period_rows(
    rows_by_period: Dict[str, List[Dict[str, Any]]],
    cap_by_period: Dict[str, float],
    *,
    round_mode: str,
) -> List[Dict[str, Any]]:
    finalized: List[Dict[str, Any]] = []
    for per in sorted(rows_by_period.keys()):
        period_rows = rows_by_period[per]
        cap_val = round_quantity(cap_by_period.get(per, 0.0), mode=round_mode)
        if round_mode == "int":
            demand_ints = [
                int(round_quantity(row["demand"], mode="int")) for row in period_rows
            ]
            supply_vals = [max(0.0, row["supply"]) for row in period_rows]
            target = min(int(cap_val), sum(demand_ints))
            target = max(0, target)
            supply_ints = distribute_int(supply_vals, target, demand_ints)
            for row, dem_int, sup_int in zip(period_rows, demand_ints, supply_ints):
                backlog_int = max(0, dem_int - sup_int)
                finalized.append(
                    {
                        "family": row["family"],
                        "period": row["period"],
                        "demand": dem_int,
                        "supply": sup_int,
                        "backlog": backlog_int,
                        "capacity_total": cap_val,
                    }
                )
        else:
            for row in period_rows:
                demand_val = round_quantity(row["demand"], mode=round_mode)
                supply_val = round_quantity(row["supply"], mode=round_mode)
                backlog_val = round_quantity(
                    max(0.0, float(demand_val) - float(supply_val)),
                    mode=round_mode,
                )
                finalized.append(
                    {
                        "family": row["family"],
                        "period": row["period"],
                        "demand": demand_val,
                        "supply": supply_val,
                        "backlog": backlog_val,
                        "capacity_total": cap_val,
                    }
                )
    return finalized


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


def _aggregate_plan(
    demand_rows: List[Dict[str, Any]],
    capacity_rows: List[Dict[str, Any]],
    *,
    round_mode: str = "int",
) -> List[Dict[str, Any]]:
    # period別の総能力
    cap_by_period: DefaultDict[str, float] = __import__("collections").defaultdict(
        float
    )
    for r in capacity_rows:
        p = str(r.get("period"))
        cap_by_period[p] += _coerce_float(r, "capacity")

    # (family, period)別の需要と period総需要
    dem_by_fp: DefaultDict[Tuple[str, str], float] = __import__(
        "collections"
    ).defaultdict(float)
    dem_sum_by_p: DefaultDict[str, float] = __import__("collections").defaultdict(float)
    families: set[str] = set()
    periods: set[str] = set()
    for r in demand_rows:
        fam = str(r.get("family"))
        per = str(r.get("period"))
        d = _coerce_float(r, "demand")
        dem_by_fp[(fam, per)] += d
        dem_sum_by_p[per] += d
        families.add(fam)
        periods.add(per)

    # 供給（不足時は比例配分）
    rows_by_period: DefaultDict[str, List[Dict[str, Any]]] = __import__(
        "collections"
    ).defaultdict(list)
    for fam, per in sorted(dem_by_fp.keys()):
        demand = dem_by_fp[(fam, per)]
        total_dem = dem_sum_by_p[per]
        total_cap = cap_by_period.get(per, 0.0)
        if total_dem <= 0:
            supply = 0.0
        elif total_cap >= total_dem:
            supply = demand
        else:
            ratio = total_cap / total_dem if total_dem > 0 else 0.0
            supply = demand * ratio
        backlog = max(0.0, demand - supply)
        rows_by_period[per].append(
            {
                "family": fam,
                "period": per,
                "demand": demand,
                "supply": supply,
                "backlog": backlog,
                "capacity_total": total_cap,
            }
        )
    return _finalize_period_rows(rows_by_period, cap_by_period, round_mode=round_mode)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="粗粒度S&OP入力の検証と雛形出力（PR1スタブ）"
    )
    ap.add_argument(
        "-i",
        "--input-dir",
        dest="input_dir",
        default=None,
        help="CSVフォルダ（demand_family.csv/capacity.csv/mix_share.csv）",
    )
    ap.add_argument("--demand", dest="demand", default=None, help="demand_family.csv")
    ap.add_argument("--capacity", dest="capacity", default=None, help="capacity.csv")
    ap.add_argument("--mix", dest="mix", default=None, help="mix_share.csv")
    ap.add_argument(
        "-o", "--output", dest="output", required=True, help="出力JSONパス（雛形）"
    )
    ap.add_argument(
        "--round",
        dest="round_mode",
        default="int",
        choices=["none", "int", "dec1", "dec2"],
        help="出力数量の丸め方法（既定:int）",
    )
    ap.add_argument(
        "--storage",
        dest="storage",
        choices=["db", "files", "both"],
        default=None,
        help="保存先: db/files/both（未指定は環境変数 PLAN_STORAGE_MODE）",
    )
    ap.add_argument(
        "--version-id",
        dest="version_id",
        default=None,
        help="PlanRepositoryへ書き込む版ID（storageにdbを含む場合は必須）",
    )
    args = ap.parse_args()

    ds = load_inputs(args.input_dir, args.demand, args.capacity, args.mix)

    rows = (
        _aggregate_plan(
            ds["demand_rows"], ds["capacity_rows"], round_mode=args.round_mode
        )
        if ds
        else []
    )

    storage_config, warning = resolve_storage_config(
        args.storage, args.version_id, cli_label="plan_aggregate"
    )
    if warning:
        print(warning, file=sys.stderr)

    payload = {
        "schema_version": "agg-1.0",
        "note": "PR2: 需要と能力に基づく粗粒度供給（不足時は比例配分）。",
        "inputs_summary": {
            "demand_rows": len(ds["demand_rows"]),
            "capacity_rows": len(ds["capacity_rows"]),
            "mix_rows": len(ds["mix_rows"]),
        },
        "rows": rows,
    }

    try:
        wrote_db = store_aggregate_payload(
            storage_config, data=payload, output_path=Path(args.output)
        )
    except PlanRepositoryError as exc:
        print(f"[error] PlanRepository書き込みに失敗しました: {exc}", file=sys.stderr)
        sys.exit(1)

    if storage_config.use_files:
        print(f"[ok] wrote {args.output}")
    if wrote_db:
        print(f"[ok] stored rows in PlanRepository version={storage_config.version_id}")


if __name__ == "__main__":
    main()
