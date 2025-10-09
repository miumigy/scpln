#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from app import db
from core.plan_repository import PlanRepositoryError
from scripts.plan_pipeline_io import (
    resolve_storage_config,
    store_report_csv_payload,
)

"""
整合ログCSVエクスポート

入力: reconciliation_log.json（before）と任意のadjusted（after）
出力: 単独CSV or 比較CSV（label列: before/after）

使い方:
  PYTHONPATH=. python3 scripts/export_reconcile_csv.py \
    -i out/reconciliation_log.json -o out/reconciliation_before.csv --label before

  PYTHONPATH=. python3 scripts/export_reconcile_csv.py \
    -i out/reconciliation_log.json --label before \
    -j out/reconciliation_log_adjusted.json --label2 after \
    -o out/reconciliation_compare.csv
"""

def _load(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _rows(payload: Dict[str, Any], label: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in payload.get("deltas", []) or []:
        out.append(
            {
                "label": label,
                "family": r.get("family"),
                "period": r.get("period"),
                "agg_demand": r.get("agg_demand"),
                "det_demand": r.get("det_demand"),
                "delta_demand": r.get("delta_demand"),
                "rel_demand": r.get("rel_demand"),
                "ok_demand": r.get("ok_demand"),
                "agg_supply": r.get("agg_supply"),
                "det_supply": r.get("det_supply"),
                "delta_supply": r.get("delta_supply"),
                "rel_supply": r.get("rel_supply"),
                "ok_supply": r.get("ok_supply"),
                "agg_backlog": r.get("agg_backlog"),
                "det_backlog": r.get("det_backlog"),
                "delta_backlog": r.get("delta_backlog"),
                "rel_backlog": r.get("rel_backlog"),
                "ok_backlog": r.get("ok_backlog"),
                "ok": r.get("ok"),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="整合ログCSVエクスポート")
    ap.add_argument("-i", dest="input1", required=True, help="reconciliation_log.json")
    ap.add_argument("-o", dest="output", required=True, help="CSV出力パス")
    ap.add_argument("--label", dest="label1", default="before", help="1つ目のラベル")
    ap.add_argument(
        "-j",
        dest="input2",
        default=None,
        help="reconciliation_log_adjusted.json（任意）",
    )
    ap.add_argument("--label2", dest="label2", default="after", help="2つ目のラベル")
    ap.add_argument(
        "--only-violations",
        dest="only_violations",
        action="store_true",
        help="違反行(ok=false)のみ出力",
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

    storage_config, warning = resolve_storage_config(
        args.storage, args.version_id, cli_label="export_reconcile_csv"
    )
    if warning:
        print(warning, file=sys.stderr)

    def _load_source(raw_path: str) -> Dict[str, Any]:
        path = Path(raw_path)
        if path.exists():
            return _load(str(path))
        if storage_config.use_db and storage_config.version_id:
            artifact = db.get_plan_artifact(storage_config.version_id, path.name)
            if artifact:
                return artifact
        raise FileNotFoundError(f"input not found: {raw_path}")

    p1 = _load_source(args.input1)
    rows = _rows(p1, args.label1)
    if args.input2:
        p2 = _load_source(args.input2)
        rows += _rows(p2, args.label2)

    if args.only_violations:
        rows = [r for r in rows if not bool(r.get("ok"))]

    fieldnames = [
        "label",
        "family",
        "period",
        "agg_demand",
        "det_demand",
        "delta_demand",
        "rel_demand",
        "ok_demand",
        "agg_supply",
        "det_supply",
        "delta_supply",
        "rel_supply",
        "ok_supply",
        "agg_backlog",
        "det_backlog",
        "delta_backlog",
        "rel_backlog",
        "ok_backlog",
        "ok",
    ]

    try:
        wrote_db = store_report_csv_payload(
            storage_config,
            rows=rows,
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
            "[ok] stored reconcile CSV in PlanRepository "
            f"version={storage_config.version_id}"
        )


if __name__ == "__main__":
    main()
