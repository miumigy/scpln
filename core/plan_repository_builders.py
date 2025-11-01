"""PlanRepository用データ生成ユーティリティ。"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any, List

from .plan_repository import PlanKpiRow, PlanSeriesRow


def _now_ms() -> int:
    return int(time.time() * 1000)


def _as_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_plan_series(
    version_id: str,
    *,
    aggregate: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> List[PlanSeriesRow]:
    rows: list[PlanSeriesRow] = []
    rows.extend(
        build_plan_series_from_aggregate(
            version_id,
            aggregate,
            default_location_key=default_location_key,
            default_location_type=default_location_type,
        )
    )
    rows.extend(
        build_plan_series_from_detail(
            version_id,
            detail,
            default_location_key=default_location_key,
            default_location_type=default_location_type,
        )
    )
    return rows


def build_plan_series_from_aggregate(
    version_id: str,
    aggregate: dict[str, Any] | None,
    *,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> List[PlanSeriesRow]:
    if not aggregate:
        return []

    rows: list[PlanSeriesRow] = []
    now = _now_ms()
    for entry in aggregate.get("rows", []):
        family = entry.get("family")
        period = entry.get("period")
        if not family or not period:
            continue
        extra = {
            "capacity_total": entry.get("capacity_total"),
            "note": aggregate.get("note"),
        }
        rows.append(
            PlanSeriesRow(
                version_id=version_id,
                level="aggregate",
                time_bucket_type="month",
                time_bucket_key=str(period),
                item_key=str(family),
                item_name=None,
                location_key=default_location_key,
                location_type=default_location_type,
                demand=_as_float(entry.get("demand")),
                supply=_as_float(entry.get("supply")),
                backlog=_as_float(entry.get("backlog")),
                capacity_used=_as_float(entry.get("capacity_total")),
                extra_json=json.dumps(extra, ensure_ascii=False),
                created_at=now,
                updated_at=now,
                source="aggregate",
            )
        )
    return rows


def build_plan_series_from_detail(
    version_id: str,
    sku_week: dict[str, Any] | None,
    *,
    default_location_key: str = "global",
    default_location_type: str = "global",
    level: str = "det",
) -> List[PlanSeriesRow]:
    if not sku_week:
        return []

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in sku_week.get("rows", []):
        sku = entry.get("sku")
        week = entry.get("week")
        if not sku or not week:
            continue
        key = (str(week), str(sku))
        bucket = grouped.setdefault(
            key,
            {
                "demand": 0.0,
                "supply": 0.0,
                "backlog": 0.0,
                "families": [],
                "periods": [],
            },
        )
        bucket["demand"] += _as_float(entry.get("demand"))
        bucket["supply"] += _as_float(entry.get("supply"))
        bucket["backlog"] += _as_float(entry.get("backlog"))

        family = entry.get("family")
        if family is not None:
            family_str = str(family)
            if family_str not in bucket["families"]:
                bucket["families"].append(family_str)

        period = entry.get("period")
        if period is not None:
            period_str = str(period)
            if period_str not in bucket["periods"]:
                bucket["periods"].append(period_str)

    rows: list[PlanSeriesRow] = []
    now = _now_ms()
    for (week, sku), bucket in grouped.items():
        families = bucket["families"]
        periods = bucket["periods"]
        primary_family = families[0] if families else None
        primary_period = periods[0] if periods else None
        extra = {
            "family": primary_family,
            "period": primary_period,
        }
        if len(families) > 1:
            extra["families"] = families
        if len(periods) > 1:
            extra["periods"] = periods

        rows.append(
            PlanSeriesRow(
                version_id=version_id,
                level=level,
                time_bucket_type="week",
                time_bucket_key=week,
                item_key=sku,
                item_name=None,
                location_key=default_location_key,
                location_type=default_location_type,
                demand=bucket["demand"],
                supply=bucket["supply"],
                backlog=bucket["backlog"],
                extra_json=json.dumps(extra, ensure_ascii=False),
                created_at=now,
                updated_at=now,
                source="allocate",
            )
        )
    return rows


def build_plan_kpis_from_aggregate(
    version_id: str,
    aggregate: dict[str, Any] | None,
) -> List[PlanKpiRow]:
    if not aggregate:
        return []

    rows = aggregate.get("rows", [])
    if not rows:
        return []

    now = _now_ms()
    total_demand = 0.0
    total_supply = 0.0
    total_backlog = 0.0
    by_period: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "demand": 0.0,
            "supply": 0.0,
            "backlog": 0.0,
        }
    )
    for entry in rows:
        period = str(entry.get("period"))
        demand = _as_float(entry.get("demand"))
        supply = _as_float(entry.get("supply"))
        backlog = _as_float(entry.get("backlog"))
        total_demand += demand
        total_supply += supply
        total_backlog += backlog
        slot = by_period[period]
        slot["demand"] += demand
        slot["supply"] += supply
        slot["backlog"] += backlog

    def _fill_rate(demand: float, supply: float) -> float:
        if demand <= 0:
            return 1.0
        return max(0.0, min(1.0, supply / demand))

    kpis: list[PlanKpiRow] = []
    for period, vals in sorted(by_period.items()):
        kpis.append(
            PlanKpiRow(
                version_id=version_id,
                metric="fill_rate",
                bucket_type="month",
                bucket_key=period,
                value=_fill_rate(vals["demand"], vals["supply"]),
                unit="ratio",
                source="aggregate",
                created_at=now,
                updated_at=now,
            )
        )
        kpis.append(
            PlanKpiRow(
                version_id=version_id,
                metric="backlog_total",
                bucket_type="month",
                bucket_key=period,
                value=vals["backlog"],
                unit="units",
                source="aggregate",
                created_at=now,
                updated_at=now,
            )
        )

    kpis.append(
        PlanKpiRow(
            version_id=version_id,
            metric="fill_rate",
            bucket_type="total",
            bucket_key="total",
            value=_fill_rate(total_demand, total_supply),
            unit="ratio",
            source="aggregate",
            created_at=now,
            updated_at=now,
        )
    )
    kpis.append(
        PlanKpiRow(
            version_id=version_id,
            metric="backlog_total",
            bucket_type="total",
            bucket_key="total",
            value=total_backlog,
            unit="units",
            source="aggregate",
            created_at=now,
            updated_at=now,
        )
    )
    kpis.append(
        PlanKpiRow(
            version_id=version_id,
            metric="demand_total",
            bucket_type="total",
            bucket_key="total",
            value=total_demand,
            unit="units",
            source="aggregate",
            created_at=now,
            updated_at=now,
        )
    )
    kpis.append(
        PlanKpiRow(
            version_id=version_id,
            metric="supply_total",
            bucket_type="total",
            bucket_key="total",
            value=total_supply,
            unit="units",
            source="aggregate",
            created_at=now,
            updated_at=now,
        )
    )
    return kpis


def build_plan_series_from_plan_final(
    version_id: str,
    plan_final: dict[str, Any] | None,
    *,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> List[PlanSeriesRow]:
    if not plan_final:
        return []

    rows: list[PlanSeriesRow] = []
    now = _now_ms()
    for entry in plan_final.get("rows", []):
        item = entry.get("item")
        week = entry.get("week")
        if not item or not week:
            continue
        extra = {
            "scheduled_receipts": entry.get("scheduled_receipts"),
            "planned_order_release": entry.get("planned_order_release"),
            "planned_order_release_adj": entry.get("planned_order_release_adj"),
            "planned_order_receipt": entry.get("planned_order_receipt"),
            "planned_order_receipt_adj": entry.get("planned_order_receipt_adj"),
            "on_hand_start": entry.get("on_hand_start"),
            "on_hand_end": entry.get("on_hand_end"),
            "lt_weeks": entry.get("lt_weeks"),
            "lot": entry.get("lot"),
            "moq": entry.get("moq"),
        }
        rows.append(
            PlanSeriesRow(
                version_id=version_id,
                level="mrp_final",
                time_bucket_type="week",
                time_bucket_key=str(week),
                item_key=str(item),
                item_name=None,
                location_key=default_location_key,
                location_type=default_location_type,
                demand=_as_float(entry.get("gross_req")),
                supply=_as_float(
                    entry.get("planned_order_receipt_adj")
                    or entry.get("planned_order_receipt")
                ),
                backlog=_as_float(entry.get("net_req")),
                inventory_open=_as_float(entry.get("on_hand_start")),
                inventory_close=_as_float(entry.get("on_hand_end")),
                extra_json=json.dumps(extra, ensure_ascii=False),
                created_at=now,
                updated_at=now,
                source="reconcile",
            )
        )
    return rows


def build_plan_series_from_weekly_summary(
    version_id: str,
    plan_final: dict[str, Any] | None,
    *,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> List[PlanSeriesRow]:
    if not plan_final:
        return []

    rows: list[PlanSeriesRow] = []
    now = _now_ms()
    for entry in plan_final.get("weekly_summary", []) or []:
        week = entry.get("week")
        if not week:
            continue
        zone = entry.get("zone")
        if not zone:
            zone = entry.get("boundary_zone")
        extra = {
            "capacity": entry.get("capacity"),
            "spill_in": entry.get("spill_in"),
            "spill_out": entry.get("spill_out"),
            "slack_carry_out": entry.get("slack_carry_out"),
            "carried_slack_in": entry.get("carried_slack_in"),
            "zone": zone,
        }
        rows.append(
            PlanSeriesRow(
                version_id=version_id,
                level="weekly_summary",
                time_bucket_type="week",
                time_bucket_key=str(week),
                item_key="summary",
                item_name=None,
                location_key=default_location_key,
                location_type=default_location_type,
                boundary_zone=str(zone) if zone is not None else None,
                demand=_as_float(entry.get("original_load")),
                supply=_as_float(entry.get("adjusted_load")),
                backlog=_as_float(entry.get("spill_out")),
                capacity_used=_as_float(entry.get("capacity")),
                extra_json=json.dumps(extra, ensure_ascii=False),
                created_at=now,
                updated_at=now,
                source="reconcile",
            )
        )
    return rows


def build_plan_series_from_mrp(
    version_id: str,
    mrp_data: dict[str, Any] | None,
    *,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> List[PlanSeriesRow]:
    if not mrp_data:
        return []

    rows: list[PlanSeriesRow] = []
    now = _now_ms()
    for entry in mrp_data.get("rows", []):
        item = entry.get("item")
        week = entry.get("week")
        if not item or not week:
            continue
        extra = {
            "scheduled_receipts": entry.get("scheduled_receipts"),
            "planned_order_release": entry.get("planned_order_release"),
            "on_hand_start": entry.get("on_hand_start"),
            "on_hand_end": entry.get("on_hand_end"),
            "lot": entry.get("lot"),
            "moq": entry.get("moq"),
            "lt_weeks": entry.get("lt_weeks"),
        }
        rows.append(
            PlanSeriesRow(
                version_id=version_id,
                level="mrp",
                time_bucket_type="week",
                time_bucket_key=str(week),
                item_key=str(item),
                item_name=None,
                location_key=default_location_key,
                location_type=default_location_type,
                demand=_as_float(entry.get("gross_req")),
                supply=_as_float(entry.get("planned_order_receipt")),
                backlog=_as_float(entry.get("net_req")),
                extra_json=json.dumps(extra, ensure_ascii=False),
                created_at=now,
                updated_at=now,
                source="mrp",
            )
        )
    return rows


def build_plan_series_from_daily(
    version_id: str,
    daily_data: dict[str, Any] | None,
    *,
    default_location_key: str = "global",
    default_location_type: str = "global",
    level: str = "daily_det",
) -> List[PlanSeriesRow]:
    if not daily_data:
        return []

    rows: list[PlanSeriesRow] = []
    now = _now_ms()
    for entry in daily_data.get("rows", []):
        item = entry.get("item")
        day = entry.get("day")
        if not item or not day:
            continue
        extra = {
            "on_hand_start": entry.get("on_hand_start"),
            "on_hand_end": entry.get("on_hand_end"),
        }
        rows.append(
            PlanSeriesRow(
                version_id=version_id,
                level=level,
                time_bucket_type="day",
                time_bucket_key=str(day),
                item_key=str(item),
                item_name=None,
                location_key=default_location_key,
                location_type=default_location_type,
                demand=_as_float(entry.get("demand")),
                supply=_as_float(entry.get("supply")),
                backlog=_as_float(entry.get("backlog")),
                inventory_open=_as_float(entry.get("on_hand_start")),
                inventory_close=_as_float(entry.get("on_hand_end")),
                extra_json=json.dumps(extra, ensure_ascii=False),
                created_at=now,
                updated_at=now,
                source="daily",
            )
        )
    return rows
