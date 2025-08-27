#!/usr/bin/env python3
"""
按分エンジン（PR3）: family→SKU、月→週の比例配分。丸めと誤差吸収をサポート。

使い方:
  python scripts/allocate.py -i out/aggregate.json -o out/sku_week.json \
    -I samples/planning --weeks 4 --round int
"""
from __future__ import annotations

import argparse
import json
import os
import csv
from typing import Dict, Any, List, Tuple


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


def _weeks_of(period: str, weeks: int) -> List[str]:
    # 期待形式 'YYYY-MM' -> 'YYYY-MM-Wk'
    base = period
    return [f"{base}-W{i}" for i in range(1, weeks + 1)]


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
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        agg = json.load(f)
    mix = _load_mix(args.input_dir, args.mix, normalize=True)

    rows_in: List[Dict[str, Any]] = agg.get("rows", [])
    weeks = max(1, int(args.weeks or 4))
    out_rows: List[Dict[str, Any]] = []

    for r in rows_in:
        fam = str(r.get("family"))
        per = str(r.get("period"))
        demand = float(r.get("demand", 0) or 0)
        supply = float(r.get("supply", 0) or 0)
        backlog = float(r.get("backlog", 0) or 0)
        pairs = mix.get(fam)
        if not pairs:
            pairs = [(fam, 1.0)]  # ミックス未定義の場合はfamily全量を仮SKUへ

        for sku, share in pairs:
            d_sku = demand * share
            s_sku = supply * share
            b_sku = backlog * share
            # 週割等分
            ws = _weeks_of(per, weeks)
            d_parts = [d_sku / weeks] * weeks
            s_parts = [s_sku / weeks] * weeks
            b_parts = [b_sku / weeks] * weeks

            # 丸め → 誤差吸収
            d_parts = _round_series(d_parts, mode=args.round_mode)
            s_parts = _round_series(s_parts, mode=args.round_mode)
            b_parts = _round_series(b_parts, mode=args.round_mode)
            d_parts = _absorb_delta(d_sku, d_parts)
            s_parts = _absorb_delta(s_sku, s_parts)
            b_parts = _absorb_delta(b_sku, b_parts)

            for i, w in enumerate(ws):
                out_rows.append(
                    {
                        "family": fam,
                        "period": per,
                        "sku": sku,
                        "week": w,
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
        },
        "rows": out_rows,
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()
