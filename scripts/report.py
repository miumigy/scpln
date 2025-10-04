#!/usr/bin/env python3
"""
KPI/レポート出力（PR6）

入力: reconcileの出力JSON（週次能力サマリとmrp行の調整済み解放/受入）
出力: 単一CSV（type列で区分）
  - type=capacity: 週別の能力/負荷/調整負荷/稼働率
  - type=service: FGの週別 需要/供給計画/概算フィルレート（scheduled+adjusted_receiptで算出）

使い方:
  python scripts/report.py -i out/plan_final.json -I samples/planning -o out/report.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, DefaultDict

from core.plan_repository import PlanRepositoryError
from scripts.plan_pipeline_io import (
    resolve_storage_config,
    store_report_csv_payload,
)


def _read_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_fg_skus(input_dir: str | None, mix_path: str | None) -> List[str]:
    path = mix_path or (os.path.join(input_dir, "mix_share.csv") if input_dir else None)
    if not path or not os.path.exists(path):
        return []
    return list({str(r.get("sku")) for r in _read_csv(path) if r.get("sku")})


def main() -> None:
    ap = argparse.ArgumentParser(description="KPI/レポート出力")
    ap.add_argument("-i", "--input", required=True, help="reconcileの出力JSON")
    ap.add_argument("-o", "--output", required=True, help="CSV出力パス")
    ap.add_argument(
        "-I",
        "--input-dir",
        dest="input_dir",
        default=None,
        help="CSVフォルダ（mix_share.csv）",
    )
    ap.add_argument("--mix", dest="mix", default=None, help="mix_share.csv（FG抽出）")
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

    storage_config, warning = resolve_storage_config(
        args.storage, args.version_id, cli_label="report"
    )
    if warning:
        print(warning, file=sys.stderr)

    with open(args.input, encoding="utf-8") as f:
        plan = json.load(f)
    rows = plan.get("rows", [])
    weeks = [r.get("week") for r in plan.get("weekly_summary", [])]
    fg_skus = set(_load_fg_skus(args.input_dir, args.mix))

    # capacityセクション
    cap_rows = []
    for r in plan.get("weekly_summary", []):
        try:
            cap = float(r.get("capacity", 0) or 0)
            adj = float(r.get("adjusted_load", 0) or 0)
        except Exception:
            cap, adj = 0.0, 0.0
        util = (adj / cap) if cap > 0 else 0.0
        cap_rows.append(
            {
                "type": "capacity",
                "week": r.get("week"),
                "capacity": round(cap, 6),
                "original_load": round(float(r.get("original_load", 0) or 0), 6),
                "adjusted_load": round(adj, 6),
                "utilization": round(util, 6),
                "spill_in": round(float(r.get("spill_in", 0) or 0), 6),
                "spill_out": round(float(r.get("spill_out", 0) or 0), 6),
            }
        )

    # serviceセクション（FGのみ集計）
    svc_rows = []
    by_week: DefaultDict[str, Dict[str, float]] = __import__("collections").defaultdict(
        lambda: {"demand": 0.0, "supply": 0.0}
    )
    for r in rows:
        it = str(r.get("item"))
        if it not in fg_skus:
            continue
        w = str(r.get("week"))
        demand = float(r.get("gross_req", 0) or 0)
        supply_plan = float(r.get("scheduled_receipts", 0) or 0) + float(
            r.get("planned_order_receipt_adj", 0) or 0
        )
        by_week[w]["demand"] += demand
        by_week[w]["supply"] += supply_plan

    for w in weeks or sorted(by_week.keys()):
        d = by_week[w]["demand"]
        s = by_week[w]["supply"]
        fill = (s / d) if d > 0 else 1.0
        svc_rows.append(
            {
                "type": "service",
                "week": w,
                "demand": round(d, 6),
                "supply_plan": round(s, 6),
                "fill_rate": round(min(1.0, fill), 6),
            }
        )

    fieldnames = [
        "type",
        "week",
        "capacity",
        "original_load",
        "adjusted_load",
        "utilization",
        "spill_in",
        "spill_out",
        "demand",
        "supply_plan",
        "fill_rate",
    ]
    all_rows = [*cap_rows, *svc_rows]

    try:
        wrote_db = store_report_csv_payload(
            storage_config,
            rows=all_rows,
            fieldnames=fieldnames,
            output_path=Path(args.output),
            artifact_name=Path(args.output).name,
        )
    except PlanRepositoryError as exc:
        print(f"[error] PlanRepository書き込みに失敗しました: {exc}", file=sys.stderr)
        sys.exit(1)

    if storage_config.use_files:
        print(f"[ok] wrote {args.output}")
    if wrote_db:
        print(
            "[ok] stored report artifact in PlanRepository "
            f"version={storage_config.version_id}"
        )


if __name__ == "__main__":
    main()
