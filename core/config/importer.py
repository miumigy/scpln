from __future__ import annotations

import json
import sys
import time
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
    log_planning_input_set_event,
)


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


def import_planning_inputs(
    directory: Path,
    config_version_id: int,
    label: str,
    apply_mode: str = "replace",
    validate_only: bool = False,
    *,
    status: str = "ready",
    source: str = "csv",
    created_by: Optional[str] = None,
    approved_by: Optional[str] = None,
    approved_at: Optional[int] = None,
    review_comment: Optional[str] = None,
) -> Dict[str, Any]:
    """
    指定されたディレクトリから計画入力を読み込み、PlanningInputSetとしてDBにインポートします。
    """
    payload = load_payload(directory)
    aggregates = payload_to_aggregates(payload)

    calendar_spec = None
    if payload.get("planning_calendar"):
        calendar_spec = PlanningCalendarSpec(**payload["planning_calendar"])

    result: Dict[str, Any] = {"status": "ok"}

    if validate_only:
        result["message"] = "validation_only"
        return result

    approval_timestamp = approved_at
    if status == "ready" and approval_timestamp is None:
        approval_timestamp = int(time.time() * 1000)

    event_actor = created_by or source

    try:
        existing = get_planning_input_set(label=label, include_aggregates=False)
    except PlanningInputSetNotFoundError:
        existing = None

    try:
        if existing:
            update_kwargs: Dict[str, Any] = {
                "label": label,
                "status": status,
                "calendar_spec": calendar_spec,
                "aggregates": aggregates,
                "replace_mode": (apply_mode == "replace"),
            }
            if status == "ready":
                if approved_by is not None:
                    update_kwargs["approved_by"] = approved_by
                update_kwargs["approved_at"] = approval_timestamp
                if review_comment is not None:
                    update_kwargs["review_comment"] = review_comment
            else:
                update_kwargs["approved_by"] = None
                update_kwargs["approved_at"] = None
                if review_comment is not None:
                    update_kwargs["review_comment"] = review_comment
            update_planning_input_set(existing.id, **update_kwargs)
            result["updated"] = existing.id
            log_planning_input_set_event(
                existing.id,
                action="update",
                actor=event_actor,
                metadata={
                    "source": source,
                    "apply_mode": apply_mode,
                    "status": status,
                },
            )
        else:
            created = create_planning_input_set(
                config_version_id=config_version_id,
                label=label,
                status=status,
                source=source,
                created_by=created_by,
                approved_by=approved_by if status == "ready" else None,
                approved_at=approval_timestamp if status == "ready" else None,
                review_comment=review_comment,
                aggregates=aggregates,
                calendar_spec=calendar_spec,
            )
            result["created"] = created.id
            log_planning_input_set_event(
                created.id,
                action="upload",
                actor=event_actor,
                metadata={
                    "source": source,
                    "apply_mode": apply_mode,
                    "status": status,
                },
            )
    except PlanningInputSetConflictError as exc:
        result["status"] = "error"
        result["message"] = f"Failed to import planning inputs: {exc}"
        return result
    except Exception as exc:
        result["status"] = "error"
        result["message"] = f"An unexpected error occurred during import: {exc}"
        return result

    return result
