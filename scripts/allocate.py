#!/usr/bin/env python3
"""
按分エンジン（PR3）: family→SKU、月→週の比例配分。丸めと誤差吸収をサポート。

使い方:
  python scripts/allocate.py -i out/aggregate.json -o out/sku_week.json \
    -I samples/planning --weeks 4 --round int
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from core.plan_repository import PlanRepositoryError
from scripts.plan_pipeline_io import (
    resolve_storage_config,
    store_allocate_payload,
)
from scripts.calendar_utils import (
    build_calendar_lookup,
    get_week_distribution,
    load_planning_calendar,
    PlanningCalendarLookup,
)
from scripts.rounding_utils import round_quantity, distribute_int


def _read_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_mix(
    input_dir: str | None, mix_path: str | None, *, normalize: bool = True
) -> Dict[str, List[Tuple[str, float]]]:
    path = mix_path or (os.path.join(input_dir, "mix_share.csv") if input_dir else None)
    mix: Dict[str, List[Tuple[str, float]]] = {}
    if path and os.path.exists(path):
        rows = _read_csv(path)
        tmp: Dict[str, List[Tuple[str, float]]] = {}
        for r in rows:
            fam = str(r.get("family"))
            sku = str(r.get("sku"))
            try:
                share = float(r.get("share"))
            except Exception:
                share = 0.0
            if not fam or not sku:
                continue
            tmp.setdefault(fam, []).append((sku, max(0.0, share)))
        for fam, pairs in tmp.items():
            s = sum(v for _, v in pairs)
            if normalize and s > 0:
                mix[fam] = [(sku, v / s) for sku, v in pairs]
            else:
                mix[fam] = pairs
    return mix


def _resolve_calendar_lookup(
    calendar_path: Optional[str], input_dir: Optional[str]
) -> Optional[PlanningCalendarLookup]:
    """カレンダーファイルを探索してLookUpを構築する。"""

    spec = None
    err: Optional[Exception] = None
    if calendar_path:
        try:
            spec = load_planning_calendar(calendar_path)
        except Exception as exc:  # validation error を含め捕捉
            err = exc
    if spec is None and input_dir:
        candidate = os.path.join(input_dir, "planning_calendar.json")
        if os.path.exists(candidate):
            try:
                spec = load_planning_calendar(candidate)
            except Exception as exc:
                err = exc
    if err:
        print(
            f"[error] planning_calendar の読み込みに失敗しました: {err}",
            file=sys.stderr,
        )
        sys.exit(1)
    if spec is None:
        return None
    return build_calendar_lookup(spec)


def _round_series(values: List[float], *, mode: str = "none") -> List[float]:
    if mode == "none":
        return values
    if mode == "int":
        rounded = [round(v) for v in values]
        return [float(x) for x in rounded]
    if mode.startswith("dec"):
        try:
            d = int(mode[3:])
        except Exception:
            d = 2
        return [round(v, d) for v in values]
    return values


def _absorb_delta(original_total: float, parts: List[float]) -> List[float]:
    # 和のズレを最後の要素に吸収
    cur = sum(parts)
    delta = original_total - cur
    if parts:
        parts[-1] += delta
    return parts


def _week_ratio_weights(entries: List[Any]) -> List[float]:
    if not entries:
        return []
    ratios = [max(0.0, getattr(entry, "ratio", 0.0)) for entry in entries]
    total = sum(ratios)
    if total <= 0:
        return [1.0 / len(entries)] * len(entries)
    return [r / total for r in ratios]


def _distribute_by_ratios(
    total: int,
    ratios: List[float],
    *,
    caps: Optional[List[int]] = None,
) -> List[int]:
    n = len(ratios)
    if n == 0:
        return []
    total_int = max(0, int(total))
    if total_int == 0:
        return [0] * n
    floats = [total_int * r for r in ratios]
    caps_int = caps[:] if caps is not None else None
    return distribute_int(floats, total_int, caps=caps_int)


def main() -> None:
    ap = argparse.ArgumentParser(description="按分（family→SKU、月→週）")
    ap.add_argument("-i", "--input", required=True, help="plan_aggregateの出力JSON")
    ap.add_argument("-o", "--output", required=True, help="出力JSON（SKU×週）")
    ap.add_argument(
        "-I",
        "--input-dir",
        dest="input_dir",
        default=None,
        help="CSVフォルダ（mix_share.csv）",
    )
    ap.add_argument("--mix", dest="mix", default=None, help="mix_share.csv のパス")
    ap.add_argument("--weeks", type=int, default=4, help="1期間あたりの週数（既定4）")
    ap.add_argument(
        "--round",
        dest="round_mode",
        default="none",
        choices=["none", "int", "dec1", "dec2"],
        help="丸め方法",
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
    ap.add_argument(
        "--calendar",
        dest="calendar",
        default=None,
        help="PlanningカレンダーJSONのパス（未指定時は input_dir から探索）",
    )
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        agg = json.load(f)
    mix = _load_mix(args.input_dir, args.mix, normalize=True)

    rows_in: List[Dict[str, Any]] = agg.get("rows", [])
    weeks = max(1, int(args.weeks or 4))
    out_rows: List[Dict[str, Any]] = []

    lookup = _resolve_calendar_lookup(args.calendar, args.input_dir)
    calendar_mode = "fallback_weeks"
    if lookup:
        calendar_mode = lookup.spec.calendar_type or "custom"

    for r in rows_in:
        fam = str(r.get("family"))
        per = str(r.get("period"))
        demand = float(r.get("demand", 0) or 0)
        supply = float(r.get("supply", 0) or 0)
        backlog = float(r.get("backlog", 0) or 0)
        pairs = mix.get(fam)
        if not pairs:
            pairs = [(fam, 1.0)]  # ミックス未定義の場合はfamily全量を仮SKUへ

        week_entries = get_week_distribution(per, lookup, weeks)
        week_ratios = _week_ratio_weights(week_entries)

        if args.round_mode == "int":
            total_d = int(round_quantity(demand, mode="int"))
            total_s = int(round_quantity(supply, mode="int"))
            shares = [max(0.0, share) for _, share in pairs]
            share_sum = sum(shares)
            if share_sum <= 0:
                shares = [1.0] * len(pairs)
                share_sum = len(pairs)
            norm_shares = [s / share_sum for s in shares]
            d_sku_ints = distribute_int(
                [total_d * s for s in norm_shares],
                total_d,
            )
            s_sku_ints = distribute_int(
                [total_s * s for s in norm_shares],
                total_s,
                caps=d_sku_ints,
            )
            b_sku_ints = [max(0, d_i - s_i) for d_i, s_i in zip(d_sku_ints, s_sku_ints)]
            for (sku, _share), d_sku_int, s_sku_int, b_sku_int in zip(
                pairs, d_sku_ints, s_sku_ints, b_sku_ints
            ):
                demand_parts = _distribute_by_ratios(d_sku_int, week_ratios)
                supply_parts = _distribute_by_ratios(
                    s_sku_int,
                    week_ratios,
                    caps=demand_parts,
                )
                backlog_parts = [
                    demand_parts[i] - supply_parts[i] for i in range(len(week_entries))
                ]
                for i, entry in enumerate(week_entries):
                    out_rows.append(
                        {
                            "family": fam,
                            "period": per,
                            "sku": sku,
                            "week": entry.week_code,
                            "demand": demand_parts[i],
                            "supply": supply_parts[i],
                            "backlog": backlog_parts[i],
                        }
                    )
            continue

        for sku, share in pairs:
            d_sku = demand * share
            s_sku = supply * share
            b_sku = backlog * share
            # カレンダーの重みで週割
            d_parts = [d_sku * week_ratios[i] for i in range(len(week_entries))]
            s_parts = [s_sku * week_ratios[i] for i in range(len(week_entries))]
            b_parts = [b_sku * week_ratios[i] for i in range(len(week_entries))]

            # 丸め → 誤差吸収
            d_parts = _round_series(d_parts, mode=args.round_mode)
            s_parts = _round_series(s_parts, mode=args.round_mode)
            b_parts = _round_series(b_parts, mode=args.round_mode)
            d_parts = _absorb_delta(d_sku, d_parts)
            s_parts = _absorb_delta(s_sku, s_parts)
            b_parts = _absorb_delta(b_sku, b_parts)

            for i, entry in enumerate(week_entries):
                out_rows.append(
                    {
                        "family": fam,
                        "period": per,
                        "sku": sku,
                        "week": entry.week_code,
                        "demand": d_parts[i],
                        "supply": s_parts[i],
                        "backlog": b_parts[i],
                    }
                )

    payload = {
        "schema_version": agg.get("schema_version", "agg-1.0"),
        "note": "PR3: family→SKU と 月→週の比例配分（丸め/誤差吸収あり）",
        "inputs_summary": {
            **agg.get("inputs_summary", {}),
            "aggregate_rows": len(rows_in),
            "mix_families": len(mix),
            "weeks_per_period": weeks,
            "round_mode": args.round_mode,
            "calendar_mode": calendar_mode,
            "calendar_periods": len(lookup.distributions) if lookup else 0,
        },
        "rows": out_rows,
    }

    storage_config, warning = resolve_storage_config(
        args.storage, args.version_id, cli_label="allocate"
    )
    if warning:
        print(warning, file=sys.stderr)

    try:
        wrote_db = store_allocate_payload(
            storage_config,
            aggregate_data=agg,
            detail_data=payload,
            output_path=Path(args.output),
        )
    except PlanRepositoryError as exc:
        print(f"[error] PlanRepository書き込みに失敗しました: {exc}", file=sys.stderr)
        sys.exit(1)

    if storage_config.use_files:
        print(f"[ok] wrote {args.output}")
    if wrote_db:
        print(
            "[ok] stored aggregate/detail rows in PlanRepository "
            f"version={storage_config.version_id}"
        )


if __name__ == "__main__":
    main()
