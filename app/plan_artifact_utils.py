from __future__ import annotations

from typing import Any, Dict, Tuple


def apply_plan_final_receipts(
    detail_obj: Dict[str, Any] | None,
    aggregate_obj: Dict[str, Any] | None,
    plan_final_obj: Dict[str, Any] | None,
) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """plan_finalに含まれる受領量 (planned_order_receipt_adj) をDET/AGGへ反映する。"""
    if not detail_obj or not isinstance(detail_obj, dict):
        return detail_obj, aggregate_obj
    if not plan_final_obj or not isinstance(plan_final_obj, dict):
        return detail_obj, aggregate_obj

    receipts: dict[tuple[str, str], float] = {}
    sku_with_receipt: set[str] = set()
    for row in plan_final_obj.get("rows", []) or []:
        sku = row.get("sku") or row.get("item")
        week = row.get("week")
        if not sku or not week:
            continue
        try:
            rec = float(
                row.get("planned_order_receipt_adj")
                if row.get("planned_order_receipt_adj") is not None
                else row.get("planned_order_receipt")
                or 0.0
            )
        except Exception:
            rec = 0.0
        key = (str(sku), str(week))
        receipts[key] = receipts.get(key, 0.0) + rec
        if rec:
            sku_with_receipt.add(str(sku))

    detail_rows: list[dict] = []
    agg_totals: dict[tuple[str, str], dict[str, float]] = {}
    for row in detail_obj.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        demand = float(row.get("demand") or 0.0)
        sku = row.get("sku")
        week = row.get("week")
        fam = row.get("family") or row.get("item")
        period = row.get("period")
        key = (str(sku), str(week))
        has_receipt_data = sku and str(sku) in sku_with_receipt
        supply = receipts.get(
            key,
            (
                0.0
                if has_receipt_data
                else (row.get("supply") or row.get("supply_plan") or 0.0)
            ),
        )
        try:
            supply_f = float(supply or 0.0)
        except Exception:
            supply_f = 0.0
        backlog = max(0.0, demand - supply_f)
        new_row = dict(row)
        new_row["supply"] = supply_f
        new_row["supply_plan"] = supply_f
        new_row["backlog"] = backlog
        detail_rows.append(new_row)

        if fam and period:
            agg_key = (str(fam), str(period))
            bucket = agg_totals.setdefault(
                agg_key, {"demand": 0.0, "supply": 0.0, "backlog": 0.0}
            )
            bucket["demand"] += demand
            bucket["supply"] += supply_f
            bucket["backlog"] += backlog

    updated_detail = dict(detail_obj)
    updated_detail["rows"] = detail_rows

    if aggregate_obj and isinstance(aggregate_obj, dict):
        agg_rows: list[dict] = []
        for row in aggregate_obj.get("rows", []) or []:
            if not isinstance(row, dict):
                continue
            fam = row.get("family")
            per = row.get("period")
            agg_row = dict(row)
            totals = agg_totals.get((str(fam), str(per)))
            if totals:
                agg_row["demand"] = totals["demand"]
                agg_row["supply"] = totals["supply"]
                if "supply_plan" in agg_row:
                    agg_row["supply_plan"] = totals["supply"]
                agg_row["backlog"] = totals["backlog"]
            agg_rows.append(agg_row)
        updated_agg = dict(aggregate_obj)
        updated_agg["rows"] = agg_rows
    else:
        updated_agg = aggregate_obj

    return updated_detail, updated_agg
