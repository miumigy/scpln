#!/usr/bin/env python3
"""
samples/planning 互換CSV/JSONから PlanningInputSet を生成し DB に登録するCLI。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config.loader import read_planning_dir
from core.config.models import (
    PlanningCapacityBucket,
    PlanningFamilyDemand,
    PlanningInboundOrder,
    PlanningInputAggregates,
    PlanningInputSet,
    PlanningInventorySnapshot,
    PlanningMixShare,
    PlanningPeriodMetric,
    PlanningCalendarSpec,
)
from core.config.storage import (
    PlanningInputSetConflictError,
    create_planning_input_set,
    update_planning_input_set,
    get_planning_input_set,
    PlanningInputSetNotFoundError,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import planning input CSV/JSON into planning_input_sets"
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        required=True,
        help="Path to samples/planning compatible directory",
    )
    parser.add_argument(
        "--version-id",
        type=int,
        help="Existing canonical config version id to attach",
    )
    parser.add_argument(
        "--new-version-id",
        type=int,
        help="Create InputSet with this config_version_id (use when metadata exists only in DB)",
    )
    parser.add_argument("--label", help="Label for the planning input set")
    parser.add_argument(
        "--apply-mode",
        choices=["merge", "replace"],
        default="replace",
        help="How to apply aggregates when updating existing InputSet",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run validation but skip DB writes",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON result to stdout for CI consumption",
    )
    parser.add_argument(
        "--report-path",
        default="tmp/import_report.json",
        help="Where to save validation/report JSON",
    )
    return parser.parse_args()


def load_payload(directory: Path) -> Dict[str, Any]:
    payload = read_planning_dir(directory)
    return payload


def payload_to_aggregates(payload: Dict[str, Any]) -> PlanningInputAggregates:
    def _float_safe(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    family = [
        PlanningFamilyDemand(
            family_code=str(row["family"]),
            period=str(row["period"]),
            demand=_float_safe(row.get("demand")),
        )
        for row in payload.get("demand_family", [])
        if row.get("family") and row.get("period")
    ]
    capacity = [
        PlanningCapacityBucket(
            resource_code=str(row.get("workcenter") or row.get("resource_code")),
            resource_type=row.get("resource_type") or "workcenter",
            period=str(row["period"]),
            capacity=_float_safe(row.get("capacity")),
        )
        for row in payload.get("capacity", [])
        if (row.get("workcenter") or row.get("resource_code")) and row.get("period")
    ]
    mix = [
        PlanningMixShare(
            family_code=str(row.get("family") or row.get("family_code")),
            sku_code=str(row.get("sku") or row.get("sku_code")),
            share=_float_safe(row.get("share")),
        )
        for row in payload.get("mix_share", [])
        if (row.get("family") or row.get("family_code"))
        and (row.get("sku") or row.get("sku_code"))
    ]
    inventory = [
        PlanningInventorySnapshot(
            node_code=str(row.get("loc") or row.get("node_code")),
            item_code=str(row.get("item") or row.get("item_code")),
            initial_qty=_float_safe(row.get("qty") or row.get("initial_qty")),
        )
        for row in payload.get("inventory", [])
        if (row.get("loc") or row.get("node_code"))
        and (row.get("item") or row.get("item_code"))
    ]
    inbound = [
        PlanningInboundOrder(
            po_id=row.get("po_id"),
            item_code=str(row.get("item") or row.get("item_code")),
            due_date=str(row.get("due") or row.get("due_date")),
            qty=_float_safe(row.get("qty")),
        )
        for row in payload.get("open_po", [])
        if (row.get("item") or row.get("item_code"))
        and (row.get("due") or row.get("due_date"))
    ]
    metrics = [
        PlanningPeriodMetric(
            metric_code="cost",
            period=str(row["period"]),
            value=_float_safe(row.get("cost")),
        )
        for row in payload.get("period_cost", [])
        if row.get("period")
    ] + [
        PlanningPeriodMetric(
            metric_code="score",
            period=str(row["period"]),
            value=_float_safe(row.get("score")),
        )
        for row in payload.get("period_score", [])
        if row.get("period")
    ]

    return PlanningInputAggregates(
        family_demands=family,
        capacity_buckets=capacity,
        mix_shares=mix,
        inventory_snapshots=inventory,
        inbound_orders=inbound,
        period_metrics=metrics,
    )


def run() -> int:
    args = parse_args()
    directory = Path(args.input_dir).resolve()
    payload = load_payload(directory)
    aggregates = payload_to_aggregates(payload)

    calendar_spec = None
    if payload.get("planning_calendar"):
        calendar_spec = PlanningCalendarSpec(**payload["planning_calendar"])

    label = args.label or f"import_{directory.name}"
    result: Dict[str, Any] = {"status": "ok"}

    if args.validate_only:
        result["message"] = "validation_only"
        _emit_result(result, args)
        return 0

    config_version_id = args.version_id or args.new_version_id
    if not config_version_id:
        print("--version-id or --new-version-id is required", file=sys.stderr)
        return 1

    try:
        existing = get_planning_input_set(label=label, include_aggregates=False)
    except PlanningInputSetNotFoundError:
        existing = None

    try:
        if existing:
            update_planning_input_set(
                existing.id,
                label=label,
                status="ready",
                calendar_spec=calendar_spec,
                aggregates=aggregates,
                replace_mode=(args.apply_mode == "replace"),
            )
            result["updated"] = existing.id
        else:
            created = create_planning_input_set(
                config_version_id=config_version_id,
                label=label,
                status="ready",
                source="csv",
                aggregates=aggregates,
                calendar_spec=calendar_spec,
            )
            result["created"] = created.id
    except PlanningInputSetConflictError as exc:
        print(f"Failed to import planning inputs: {exc}", file=sys.stderr)
        return 2

    _emit_result(result, args)
    return 0


def _emit_result(result: Dict[str, Any], args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(result))
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(run())
