#!/usr/bin/env python3
"""
planning_input_sets から samples/planning 互換CSV/JSONを出力するCLI。
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import shutil
import sys

from core.config.storage import (
    get_planning_input_set,
    list_planning_input_sets,
    PlanningInputSetNotFoundError,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export planning_input_sets into samples/planning format"
    )
    parser.add_argument(
        "--version-id",
        type=int,
        help="Canonical version id whose latest ready InputSet will be exported",
    )
    parser.add_argument(
        "--label",
        help="Export InputSet by label (takes precedence over version-id)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Directory to output CSV files (default: out/planning_inputs_<label>)",
    )
    parser.add_argument(
        "--include-meta",
        action="store_true",
        help="Emit planning_params.json and input_set_meta.json",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Pack outputs into zip archive (output-dir.zip)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON result to stdout",
    )
    parser.add_argument(
        "--diff-against",
        help="Label of InputSet to diff against (diff_report.json is emitted)",
    )
    return parser.parse_args()


def ensure_output_dir(base_dir: Optional[str], label: str) -> Path:
    if base_dir:
        out_dir = Path(base_dir).resolve()
    else:
        out_dir = Path("out") / f"planning_inputs_{label}"
        out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def write_csv(path: Path, rows: Iterable[Dict[str, object]], fieldnames: List[str]):
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def export_input_set(args: argparse.Namespace) -> Dict[str, object]:
    input_set = _resolve_input_set(args)
    label = args.label or input_set.label
    output_dir = ensure_output_dir(args.output_dir, label)

    aggregate = input_set.aggregates
    write_csv(
        output_dir / "demand_family.csv",
        [{"family": r.family_code, "period": r.period, "demand": r.demand} for r in aggregate.family_demands],
        ["family", "period", "demand"],
    )
    write_csv(
        output_dir / "capacity.csv",
        [
            {
                "workcenter": r.resource_code,
                "period": r.period,
                "capacity": r.capacity,
            }
            for r in aggregate.capacity_buckets
        ],
        ["workcenter", "period", "capacity"],
    )
    write_csv(
        output_dir / "mix_share.csv",
        [
            {"family": r.family_code, "sku": r.sku_code, "share": r.share}
            for r in aggregate.mix_shares
        ],
        ["family", "sku", "share"],
    )
    write_csv(
        output_dir / "inventory.csv",
        [
            {"loc": r.node_code, "item": r.item_code, "qty": r.initial_qty}
            for r in aggregate.inventory_snapshots
        ],
        ["loc", "item", "qty"],
    )
    write_csv(
        output_dir / "open_po.csv",
        [
            {"item": r.item_code, "due": r.due_date, "qty": r.qty}
            for r in aggregate.inbound_orders
        ],
        ["item", "due", "qty"],
    )
    write_csv(
        output_dir / "period_cost.csv",
        [
            {"period": m.period, "cost": m.value}
            for m in aggregate.period_metrics
            if m.metric_code == "cost"
        ],
        ["period", "cost"],
    )
    write_csv(
        output_dir / "period_score.csv",
        [
            {"period": m.period, "score": m.value}
            for m in aggregate.period_metrics
            if m.metric_code == "score"
        ],
        ["period", "score"],
    )

    if input_set.calendar_spec:
        with (output_dir / "planning_calendar.json").open("w", encoding="utf-8") as fp:
            json.dump(input_set.calendar_spec.model_dump(mode="json"), fp, ensure_ascii=False, indent=2)

    if args.include_meta:
        meta = {
            "id": input_set.id,
            "label": input_set.label,
            "status": input_set.status,
            "config_version_id": input_set.config_version_id,
            "source": input_set.source,
            "created_at": input_set.created_at,
            "updated_at": input_set.updated_at,
        }
        with (output_dir / "input_set_meta.json").open("w", encoding="utf-8") as fp:
            json.dump(meta, fp, ensure_ascii=False, indent=2)
        if input_set.planning_params:
            with (output_dir / "planning_params.json").open("w", encoding="utf-8") as fp:
                json.dump(input_set.planning_params.model_dump(mode="json"), fp, ensure_ascii=False, indent=2)

    if args.diff_against:
        diff = _build_diff_report(input_set, args.diff_against)
        with (output_dir / "diff_report.json").open("w", encoding="utf-8") as fp:
            json.dump(diff, fp, ensure_ascii=False, indent=2)

    if args.zip:
        archive = shutil.make_archive(str(output_dir), "zip", root_dir=output_dir)
        result_path = archive
    else:
        result_path = str(output_dir)

    result = {"status": "ok", "output": result_path}
    _emit_json(result, args)
    return result


def _build_diff_report(current, other_label: str) -> Dict[str, List[Dict[str, object]]]:
    try:
        other = get_planning_input_set(label=other_label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        return {"error": f"diff target {other_label} not found"}

    def _agg_to_map(records, key_fields):
        mapping = {}
        for rec in records:
            key = tuple(getattr(rec, field) for field in key_fields)
            mapping[key] = rec
        return mapping

    def _diff_lists(curr, prev, key_fields):
        curr_map = _agg_to_map(curr, key_fields)
        prev_map = _agg_to_map(prev, key_fields)
        added = [curr_map[k].model_dump() if hasattr(curr_map[k], "model_dump") else curr_map[k].__dict__ for k in curr_map.keys() - prev_map.keys()]
        removed = [prev_map[k].model_dump() if hasattr(prev_map[k], "model_dump") else prev_map[k].__dict__ for k in prev_map.keys() - curr_map.keys()]
        changed = []
        for key in curr_map.keys() & prev_map.keys():
            curr_row = curr_map[key]
            prev_row = prev_map[key]
            if curr_row != prev_row:
                changed.append({"current": curr_row.model_dump(), "previous": prev_row.model_dump()})
        return {"added": added, "removed": removed, "changed": changed}

    curr = current.aggregates
    prev = other.aggregates
    return {
        "demand_family": _diff_lists(curr.family_demands, prev.family_demands, ["family_code", "period"]),
        "capacity": _diff_lists(curr.capacity_buckets, prev.capacity_buckets, ["resource_code", "period"]),
        "mix_share": _diff_lists(curr.mix_shares, prev.mix_shares, ["family_code", "sku_code"]),
        "inventory": _diff_lists(curr.inventory_snapshots, prev.inventory_snapshots, ["node_code", "item_code"]),
        "open_po": _diff_lists(curr.inbound_orders, prev.inbound_orders, ["item_code", "due_date"]),
        "period_metrics": _diff_lists(curr.period_metrics, prev.period_metrics, ["metric_code", "period"]),
    }


def _resolve_input_set(args: argparse.Namespace):
    if args.label:
        return get_planning_input_set(label=args.label, include_aggregates=True)
    if args.version_id:
        summaries = list_planning_input_sets(config_version_id=args.version_id, status="ready", limit=1)
        if not summaries:
            raise SystemExit(f"No InputSet found for version {args.version_id}")
        return get_planning_input_set(input_set_id=summaries[0].id, include_aggregates=True)
    raise SystemExit("--label or --version-id must be specified")


def _emit_json(result: Dict[str, object], args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(result))


def main() -> int:
    args = parse_args()
    try:
        export_input_set(args)
    except PlanningInputSetNotFoundError as exc:
        print(f"InputSet not found: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
