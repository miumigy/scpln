"""Canonical設定の永続化レイヤー。"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.db import _conn

from core.sorting import natural_sort_key

from .models import (
    CalendarDefinition,
    CanonicalArc,
    CanonicalBom,
    CanonicalConfig,
    CanonicalItem,
    CanonicalNode,
    CapacityProfile,
    ConfigMeta,
    DemandProfile,
    HierarchyEntry,
    NodeInventoryPolicy,
    NodeProductionPolicy,
    PlanningCapacityBucket,
    PlanningFamilyDemand,
    PlanningInboundOrder,
    PlanningInputAggregates,
    PlanningInputSet,
    PlanningInputSetEvent,
    PlanningInventorySnapshot,
    PlanningMixShare,
    PlanningPeriodMetric,
    PlanningCalendarSpec,
    PlanningParams,
)
from .validators import ValidationResult, validate_canonical_config


class PlanningInputSetNotFoundError(Exception):
    """指定されたPlanningInputSetが見つからない場合に送出。"""


class PlanningInputSetConflictError(Exception):
    """ユニーク制約などでInputSetを作成できなかった場合に送出。"""


@dataclass
class PlanningInputSetSummary:
    id: int
    config_version_id: int
    label: str
    status: str
    source: str
    created_at: Optional[int]
    updated_at: Optional[int]
    approved_by: Optional[str] = None
    approved_at: Optional[int] = None
    review_comment: Optional[str] = None


_UNSET = object()


def _row_to_meta(row: sqlite3.Row) -> ConfigMeta:
    return ConfigMeta(
        version_id=row["id"],
        name=row["name"],
        schema_version=row["schema_version"],
        version_tag=row["version_tag"],
        status=row["status"],
        description=row["description"],
        source_config_id=row["source_config_id"],
        parent_version_id=row["parent_version_id"],
        is_deleted=bool(row["is_deleted"]),
        attributes=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_meta(row: sqlite3.Row) -> ConfigMeta:
    return ConfigMeta(
        version_id=row["id"],
        name=row["name"],
        schema_version=row["schema_version"],
        version_tag=row["version_tag"],
        status=row["status"],
        description=row["description"],
        source_config_id=row["source_config_id"],
        parent_version_id=row["parent_version_id"],
        is_deleted=bool(row["is_deleted"]),
        attributes=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_item(row: sqlite3.Row) -> CanonicalItem:
    return CanonicalItem(
        code=row["item_code"],
        name=row["item_name"],
        item_type=row["item_type"],
        uom=row["uom"],
        lead_time_days=row["lead_time_days"],
        lot_size=row["lot_size"],
        min_order_qty=row["min_order_qty"],
        safety_stock=row["safety_stock"],
        unit_cost=row["unit_cost"],
        attributes=json.loads(row["attributes_json"]) if row["attributes_json"] else {},
    )


def _row_to_node(
    row: sqlite3.Row,
    inventory_map: Dict[str, List[NodeInventoryPolicy]],
    production_map: Dict[str, List[NodeProductionPolicy]],
) -> CanonicalNode:
    node_code = row["node_code"]
    return CanonicalNode(
        code=node_code,
        name=row["node_name"],
        node_type=row["node_type"],
        timezone=row["timezone"],
        region=row["region"],
        service_level=row["service_level"],
        lead_time_days=row["lead_time_days"],
        storage_capacity=row["storage_capacity"],
        allow_storage_over_capacity=bool(row["allow_storage_over_capacity"]),
        storage_cost_fixed=row["storage_cost_fixed"],
        storage_over_capacity_fixed_cost=row["storage_over_capacity_fixed_cost"],
        storage_over_capacity_variable_cost=row["storage_over_capacity_variable_cost"],
        review_period_days=row["review_period_days"],
        inventory_policies=inventory_map.get(node_code, []),
        production_policies=production_map.get(node_code, []),
        attributes=json.loads(row["attributes_json"]) if row["attributes_json"] else {},
    )


def _row_to_arc(row: sqlite3.Row) -> CanonicalArc:
    return CanonicalArc(
        from_node=row["from_node"],
        to_node=row["to_node"],
        arc_type=row["arc_type"],
        lead_time_days=row["lead_time_days"],
        capacity_per_day=row["capacity_per_day"],
        allow_over_capacity=bool(row["allow_over_capacity"]),
        transportation_cost_fixed=row["transportation_cost_fixed"],
        transportation_cost_variable=row["transportation_cost_variable"],
        min_order_qty=(
            json.loads(row["min_order_json"]) if row["min_order_json"] else {}
        ),
        order_multiple=(
            json.loads(row["order_multiple_json"]) if row["order_multiple_json"] else {}
        ),
        attributes=json.loads(row["attributes_json"]) if row["attributes_json"] else {},
    )


def _row_to_bom(row: sqlite3.Row) -> CanonicalBom:
    return CanonicalBom(
        parent_item=row["parent_item"],
        child_item=row["child_item"],
        quantity=row["quantity"],
        scrap_rate=row["scrap_rate"],
        attributes=json.loads(row["attributes_json"]) if row["attributes_json"] else {},
    )


def _row_to_demand(row: sqlite3.Row) -> DemandProfile:
    return DemandProfile(
        node_code=row["node_code"],
        item_code=row["item_code"],
        bucket=row["bucket"],
        demand_model=row["demand_model"],
        mean=row["mean"],
        std_dev=row["std_dev"],
        min_qty=row["min_qty"],
        max_qty=row["max_qty"],
        attributes=json.loads(row["attributes_json"]) if row["attributes_json"] else {},
    )


def _row_to_capacity(row: sqlite3.Row) -> CapacityProfile:
    return CapacityProfile(
        resource_code=row["resource_code"],
        resource_type=row["resource_type"],
        bucket=row["bucket"],
        capacity=row["capacity"],
        calendar_code=row["calendar_code"],
        attributes=json.loads(row["attributes_json"]) if row["attributes_json"] else {},
    )


def _row_to_hierarchy(row: sqlite3.Row) -> HierarchyEntry:
    return HierarchyEntry(
        hierarchy_type=row["hierarchy_type"],
        node_key=row["node_key"],
        parent_key=row["parent_key"],
        level=row["level"],
        sort_order=row["sort_order"],
        attributes=json.loads(row["attributes_json"]) if row["attributes_json"] else {},
    )


def _row_to_calendar(row: sqlite3.Row) -> CalendarDefinition:
    return CalendarDefinition(
        calendar_code=row["calendar_code"],
        timezone=row["timezone"],
        definition=json.loads(row["definition_json"]) if row["definition_json"] else {},
        attributes=json.loads(row["attributes_json"]) if row["attributes_json"] else {},
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _json_loads(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _row_to_planning_input_set(
    row: sqlite3.Row, aggregates: PlanningInputAggregates
) -> PlanningInputSet:
    calendar_spec = None
    if row["calendar_spec_json"]:
        try:
            calendar_spec = PlanningCalendarSpec(**json.loads(row["calendar_spec_json"]))
        except Exception:
            calendar_spec = None
    planning_params = None
    if row["planning_params_json"]:
        try:
            planning_params = PlanningParams(**json.loads(row["planning_params_json"]))
        except Exception:
            planning_params = None

    return PlanningInputSet(
        id=row["id"],
        config_version_id=row["config_version_id"],
        label=row["label"],
        status=row["status"],
        source=row["source"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
        review_comment=row["review_comment"],
        metadata=_json_loads(row["metadata_json"]),
        calendar_spec=calendar_spec,
        planning_params=planning_params,
        aggregates=aggregates,
    )


def _row_to_planning_input_set_event(row: sqlite3.Row) -> PlanningInputSetEvent:
    return PlanningInputSetEvent(
        id=row["id"],
        input_set_id=row["input_set_id"],
        action=row["action"],
        actor=row["actor"],
        comment=row["comment"],
        metadata=_json_loads(row["metadata_json"]),
        created_at=row["created_at"],
    )


def _load_planning_input_aggregates(
    cur: sqlite3.Cursor, input_set_id: int
) -> PlanningInputAggregates:
    return PlanningInputAggregates(
        family_demands=_load_family_demands(cur, input_set_id),
        capacity_buckets=_load_capacity_buckets(cur, input_set_id),
        mix_shares=_load_mix_shares(cur, input_set_id),
        inventory_snapshots=_load_inventory_snapshots(cur, input_set_id),
        inbound_orders=_load_inbound_orders(cur, input_set_id),
        period_metrics=_load_period_metrics(cur, input_set_id),
    )


def _load_family_demands(
    cur: sqlite3.Cursor, input_set_id: int
) -> List[PlanningFamilyDemand]:
    rows = cur.execute(
        """
        SELECT family_code, period, demand, source_type, tolerance_abs, attributes_json
        FROM planning_family_demands
        WHERE input_set_id = ?
        ORDER BY family_code, period
        """,
        (input_set_id,),
    ).fetchall()
    return [
        PlanningFamilyDemand(
            family_code=row["family_code"],
            period=row["period"],
            demand=row["demand"],
            source_type=row["source_type"],
            tolerance_abs=row["tolerance_abs"],
            attributes=_json_loads(row["attributes_json"]),
        )
        for row in rows
    ]


def _load_capacity_buckets(
    cur: sqlite3.Cursor, input_set_id: int
) -> List[PlanningCapacityBucket]:
    rows = cur.execute(
        """
        SELECT resource_code, resource_type, period, capacity, calendar_code, attributes_json
        FROM planning_capacity_buckets
        WHERE input_set_id = ?
        ORDER BY resource_code, period
        """,
        (input_set_id,),
    ).fetchall()
    return [
        PlanningCapacityBucket(
            resource_code=row["resource_code"],
            resource_type=row["resource_type"],
            period=row["period"],
            capacity=row["capacity"],
            calendar_code=row["calendar_code"],
            attributes=_json_loads(row["attributes_json"]),
        )
        for row in rows
    ]


def _load_mix_shares(
    cur: sqlite3.Cursor, input_set_id: int
) -> List[PlanningMixShare]:
    rows = cur.execute(
        """
        SELECT family_code, sku_code, share, effective_from, effective_to,
               weight_source, attributes_json
        FROM planning_mix_shares
        WHERE input_set_id = ?
        ORDER BY family_code, sku_code, effective_from
        """,
        (input_set_id,),
    ).fetchall()
    return [
        PlanningMixShare(
            family_code=row["family_code"],
            sku_code=row["sku_code"],
            share=row["share"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            weight_source=row["weight_source"],
            attributes=_json_loads(row["attributes_json"]),
        )
        for row in rows
    ]


def _load_inventory_snapshots(
    cur: sqlite3.Cursor, input_set_id: int
) -> List[PlanningInventorySnapshot]:
    rows = cur.execute(
        """
        SELECT node_code, item_code, initial_qty, reorder_point, order_up_to,
               safety_stock, attributes_json
        FROM planning_inventory_snapshots
        WHERE input_set_id = ?
        ORDER BY node_code, item_code
        """,
        (input_set_id,),
    ).fetchall()
    return [
        PlanningInventorySnapshot(
            node_code=row["node_code"],
            item_code=row["item_code"],
            initial_qty=row["initial_qty"],
            reorder_point=row["reorder_point"],
            order_up_to=row["order_up_to"],
            safety_stock=row["safety_stock"],
            attributes=_json_loads(row["attributes_json"]),
        )
        for row in rows
    ]


def _load_inbound_orders(
    cur: sqlite3.Cursor, input_set_id: int
) -> List[PlanningInboundOrder]:
    rows = cur.execute(
        """
        SELECT po_id, item_code, source_node, dest_node, due_date, qty, attributes_json
        FROM planning_inbound_orders
        WHERE input_set_id = ?
        ORDER BY due_date, item_code
        """,
        (input_set_id,),
    ).fetchall()
    return [
        PlanningInboundOrder(
            po_id=row["po_id"],
            item_code=row["item_code"],
            source_node=row["source_node"],
            dest_node=row["dest_node"],
            due_date=row["due_date"],
            qty=row["qty"],
            attributes=_json_loads(row["attributes_json"]),
        )
        for row in rows
    ]


def _load_period_metrics(
    cur: sqlite3.Cursor, input_set_id: int
) -> List[PlanningPeriodMetric]:
    rows = cur.execute(
        """
        SELECT metric_code, period, value, unit, source, attributes_json
        FROM planning_period_metrics
        WHERE input_set_id = ?
        ORDER BY metric_code, period
        """,
        (input_set_id,),
    ).fetchall()
    return [
        PlanningPeriodMetric(
            metric_code=row["metric_code"],
            period=row["period"],
            value=row["value"],
            unit=row["unit"],
            source=row["source"],
            attributes=_json_loads(row["attributes_json"]),
        )
        for row in rows
    ]


def _replace_planning_aggregates(
    cur: sqlite3.Cursor, input_set_id: int, aggregates: PlanningInputAggregates
) -> None:
    cur.execute("DELETE FROM planning_family_demands WHERE input_set_id=?", (input_set_id,))
    cur.execute("DELETE FROM planning_capacity_buckets WHERE input_set_id=?", (input_set_id,))
    cur.execute("DELETE FROM planning_mix_shares WHERE input_set_id=?", (input_set_id,))
    cur.execute(
        "DELETE FROM planning_inventory_snapshots WHERE input_set_id=?", (input_set_id,)
    )
    cur.execute("DELETE FROM planning_inbound_orders WHERE input_set_id=?", (input_set_id,))
    cur.execute("DELETE FROM planning_period_metrics WHERE input_set_id=?", (input_set_id,))

    if aggregates.family_demands:
        cur.executemany(
            """
            INSERT INTO planning_family_demands(
                input_set_id, family_code, period, demand, source_type, tolerance_abs,
                attributes_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            [
                (
                    input_set_id,
                    row.family_code,
                    row.period,
                    row.demand,
                    row.source_type,
                    row.tolerance_abs,
                    _json_dumps(row.attributes),
                )
                for row in aggregates.family_demands
            ],
        )

    if aggregates.capacity_buckets:
        cur.executemany(
            """
            INSERT INTO planning_capacity_buckets(
                input_set_id, resource_code, resource_type, period, capacity,
                calendar_code, attributes_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            [
                (
                    input_set_id,
                    row.resource_code,
                    row.resource_type,
                    row.period,
                    row.capacity,
                    row.calendar_code,
                    _json_dumps(row.attributes),
                )
                for row in aggregates.capacity_buckets
            ],
        )

    if aggregates.mix_shares:
        cur.executemany(
            """
            INSERT INTO planning_mix_shares(
                input_set_id, family_code, sku_code, share, effective_from, effective_to,
                weight_source, attributes_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            [
                (
                    input_set_id,
                    row.family_code,
                    row.sku_code,
                    row.share,
                    row.effective_from,
                    row.effective_to,
                    row.weight_source,
                    _json_dumps(row.attributes),
                )
                for row in aggregates.mix_shares
            ],
        )

    if aggregates.inventory_snapshots:
        cur.executemany(
            """
            INSERT INTO planning_inventory_snapshots(
                input_set_id, node_code, item_code, initial_qty, reorder_point,
                order_up_to, safety_stock, attributes_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            [
                (
                    input_set_id,
                    row.node_code,
                    row.item_code,
                    row.initial_qty,
                    row.reorder_point,
                    row.order_up_to,
                    row.safety_stock,
                    _json_dumps(row.attributes),
                )
                for row in aggregates.inventory_snapshots
            ],
        )

    if aggregates.inbound_orders:
        cur.executemany(
            """
            INSERT INTO planning_inbound_orders(
                input_set_id, po_id, item_code, source_node, dest_node, due_date,
                qty, attributes_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            [
                (
                    input_set_id,
                    row.po_id,
                    row.item_code,
                    row.source_node,
                    row.dest_node,
                    row.due_date,
                    row.qty,
                    _json_dumps(row.attributes),
                )
                for row in aggregates.inbound_orders
            ],
        )

    if aggregates.period_metrics:
        cur.executemany(
            """
            INSERT INTO planning_period_metrics(
                input_set_id, metric_code, period, value, unit, source, attributes_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            [
                (
                    input_set_id,
                    row.metric_code,
                    row.period,
                    row.value,
                    row.unit,
                    row.source,
                    _json_dumps(row.attributes),
                )
                for row in aggregates.period_metrics
            ],
        )


def _group_inventory(rows: List[sqlite3.Row]) -> Dict[str, List[NodeInventoryPolicy]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["node_code"]].append(
            NodeInventoryPolicy(
                item_code=row["item_code"],
                initial_inventory=row["initial_inventory"],
                reorder_point=row["reorder_point"],
                order_up_to=row["order_up_to"],
                min_order_qty=row["min_order_qty"],
                order_multiple=row["order_multiple"],
                safety_stock=row["safety_stock"],
                storage_cost=row["storage_cost"],
                stockout_cost=row["stockout_cost"],
                backorder_cost=row["backorder_cost"],
                lead_time_days=row["lead_time_days"],
                attributes=(
                    json.loads(row["attributes_json"]) if row["attributes_json"] else {}
                ),
            )
        )
    return grouped


def _group_production(rows: List[sqlite3.Row]) -> Dict[str, List[NodeProductionPolicy]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["node_code"]].append(
            NodeProductionPolicy(
                item_code=row["item_code"],
                production_capacity=row["production_capacity"],
                allow_over_capacity=bool(row["allow_over_capacity"]),
                over_capacity_fixed_cost=row["over_capacity_fixed_cost"],
                over_capacity_variable_cost=row["over_capacity_variable_cost"],
                production_cost_fixed=row["production_cost_fixed"],
                production_cost_variable=row["production_cost_variable"],
                attributes=(
                    json.loads(row["attributes_json"]) if row["attributes_json"] else {}
                ),
            )
        )
    return grouped


@dataclass
class CanonicalVersionSummary:
    """Canonical設定のメタ情報と件数サマリ。"""

    meta: ConfigMeta
    counts: Dict[str, int]


class CanonicalConfigNotFoundError(RuntimeError):
    """指定したIDのCanonical設定が見つからない場合に送出。"""


def list_canonical_versions(
    *, limit: int = 50, db_path: Optional[str] = None, include_deleted: bool = False
) -> List[ConfigMeta]:
    """保存済みCanonical設定のメタ情報を取得する。"""
    path = _resolve_db_path(db_path)
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:

        query = """


            SELECT id, name, schema_version, version_tag, status, description,


                   source_config_id, parent_version_id, is_deleted, metadata_json, created_at, updated_at


            FROM canonical_config_versions


        """

        params: List[Any] = []

        if not include_deleted:

            query += " WHERE is_deleted = 0"

        query += " ORDER BY id DESC LIMIT ?"

        params.append(limit)

        rows = cur.execute(query, params).fetchall()

    metas: List[ConfigMeta] = []

    for row in rows:

        metas.append(_row_to_meta(row))

    return metas


def list_canonical_version_summaries(
    *, limit: int = 50, db_path: Optional[str] = None, include_deleted: bool = False
) -> List[CanonicalVersionSummary]:
    """メタ情報に加えて主要テーブル件数を含むサマリを取得する。"""

    metas = list_canonical_versions(
        limit=limit, db_path=db_path, include_deleted=include_deleted
    )
    if not metas:
        return []

    if os.getenv("SCPLN_CANONICAL_SKIP_COUNTS"):
        return [
            CanonicalVersionSummary(meta=meta, counts=_default_counts())
            for meta in metas
        ]

    path = _resolve_db_path(db_path)
    counts_map: Dict[int, Dict[str, int]] = {}
    missing_ids: List[int] = []
    for meta in metas:
        vid = meta.version_id
        if vid is None:
            continue
        attr_counts = (meta.attributes or {}).get("counts")
        if _is_valid_counts(attr_counts):
            counts_map[vid] = attr_counts  # type: ignore[arg-type]
        else:
            missing_ids.append(vid)

    if missing_ids:
        fetched = _collect_counts(missing_ids, path)
        for vid, counts in fetched.items():
            counts_map[vid] = counts
        _update_counts_metadata(path, metas, fetched)

    summaries: List[CanonicalVersionSummary] = []
    for meta in metas:
        vid = meta.version_id or -1
        summaries.append(
            CanonicalVersionSummary(
                meta=meta,
                counts=counts_map.get(vid, _default_counts()),
            )
        )
    return summaries


def get_canonical_config(
    version_id: int, *, db_path: Optional[str] = None
) -> CanonicalConfig:
    """指定IDのCanonical設定を復元する。"""

    path = _resolve_db_path(db_path)
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        meta_row = cur.execute(
            """
            SELECT id, name, schema_version, version_tag, status, description,
                   source_config_id, parent_version_id, is_deleted, metadata_json, created_at, updated_at
            FROM canonical_config_versions
            WHERE id=? AND is_deleted = 0
            """,
            (version_id,),
        ).fetchone()
        if not meta_row:
            raise CanonicalConfigNotFoundError(
                f"config version id={version_id} not found"
            )

        item_rows = cur.execute(
            """
            SELECT item_code, item_name, item_type, uom, lead_time_days,
                   lot_size, min_order_qty, safety_stock, unit_cost, attributes_json
            FROM canonical_items
            WHERE config_version_id=?
            ORDER BY item_code
            """,
            (version_id,),
        ).fetchall()

        node_rows = cur.execute(
            """
            SELECT node_code, node_name, node_type, timezone, region, service_level,
                   lead_time_days, storage_capacity, allow_storage_over_capacity,
                   storage_cost_fixed, storage_over_capacity_fixed_cost,
                   storage_over_capacity_variable_cost, review_period_days,
                   attributes_json
            FROM canonical_nodes
            WHERE config_version_id=?
            ORDER BY node_code
            """,
            (version_id,),
        ).fetchall()

        inv_rows = cur.execute(
            """
            SELECT node_code, item_code, initial_inventory, reorder_point, order_up_to,
                   min_order_qty, order_multiple, safety_stock, storage_cost,
                   stockout_cost, backorder_cost, lead_time_days, attributes_json
            FROM canonical_node_items
            WHERE config_version_id=?
            ORDER BY node_code, item_code
            """,
            (version_id,),
        ).fetchall()

        prod_rows = cur.execute(
            """
            SELECT node_code, item_code, production_capacity, allow_over_capacity,
                   over_capacity_fixed_cost, over_capacity_variable_cost,
                   production_cost_fixed, production_cost_variable, attributes_json
            FROM canonical_node_production
            WHERE config_version_id=?
            ORDER BY node_code, item_code
            """,
            (version_id,),
        ).fetchall()

        arc_rows = cur.execute(
            """
            SELECT from_node, to_node, arc_type, lead_time_days, capacity_per_day,
                   allow_over_capacity, transportation_cost_fixed,
                   transportation_cost_variable, min_order_json,
                   order_multiple_json, attributes_json
            FROM canonical_arcs
            WHERE config_version_id=?
            ORDER BY from_node, to_node, arc_type
            """,
            (version_id,),
        ).fetchall()

        bom_rows = cur.execute(
            """
            SELECT parent_item, child_item, quantity, scrap_rate, attributes_json
            FROM canonical_boms
            WHERE config_version_id=?
            ORDER BY parent_item, child_item
            """,
            (version_id,),
        ).fetchall()

        demand_rows = cur.execute(
            """
            SELECT node_code, item_code, bucket, demand_model, mean, std_dev,
                   min_qty, max_qty, attributes_json
            FROM canonical_demands
            WHERE config_version_id=?
            ORDER BY node_code, item_code, bucket
            """,
            (version_id,),
        ).fetchall()

        capacity_rows = cur.execute(
            """
            SELECT resource_code, resource_type, bucket, capacity, calendar_code,
                   attributes_json
            FROM canonical_capacities
            WHERE config_version_id=?
            ORDER BY resource_type, resource_code, bucket
            """,
            (version_id,),
        ).fetchall()

        hierarchy_rows = cur.execute(
            """
            SELECT hierarchy_type, node_key, parent_key, level, sort_order,
                   attributes_json
            FROM canonical_hierarchies
            WHERE config_version_id=?
            ORDER BY hierarchy_type, node_key
            """,
            (version_id,),
        ).fetchall()

        calendar_rows = cur.execute(
            """
            SELECT calendar_code, timezone, definition_json, attributes_json
            FROM canonical_calendars
            WHERE config_version_id=?
            ORDER BY calendar_code
            """,
            (version_id,),
        ).fetchall()

    meta = _row_to_meta(meta_row)
    items = [_row_to_item(row) for row in item_rows]
    inventory_map = _group_inventory(inv_rows)
    production_map = _group_production(prod_rows)
    nodes = [_row_to_node(row, inventory_map, production_map) for row in node_rows]
    arcs = [_row_to_arc(row) for row in arc_rows]
    bom = [_row_to_bom(row) for row in bom_rows]
    demands = sorted(
        (_row_to_demand(row) for row in demand_rows),
        key=lambda d: (
            d.node_code or "",
            d.item_code or "",
            natural_sort_key(d.bucket),
        ),
    )
    capacities = sorted(
        (_row_to_capacity(row) for row in capacity_rows),
        key=lambda c: (
            c.resource_type or "",
            c.resource_code or "",
            natural_sort_key(c.bucket),
        ),
    )
    hierarchies = [_row_to_hierarchy(row) for row in hierarchy_rows]
    calendars = [_row_to_calendar(row) for row in calendar_rows]

    return CanonicalConfig(
        meta=meta,
        items=items,
        nodes=nodes,
        arcs=arcs,
        bom=bom,
        demands=demands,
        capacities=capacities,
        calendars=calendars,
        hierarchies=hierarchies,
    )


def load_canonical_config_from_db(
    version_id: int,
    *,
    db_path: Optional[str] = None,
    validate: bool = False,
) -> tuple[CanonicalConfig, Optional[ValidationResult]]:
    """DBから設定を読み込み、任意で整合チェックを実施する。"""

    config = get_canonical_config(version_id, db_path=db_path)
    validation: Optional[ValidationResult] = None
    if validate:
        validation = validate_canonical_config(config)
    return config, validation


def save_canonical_config(
    config: CanonicalConfig,
    *,
    db_path: Optional[str] = None,
) -> int:
    """Canonical設定をDBへ保存し、新しいversion_idを返す。"""

    path = _resolve_db_path(db_path)
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        version_id = _insert_canonical_snapshot(cur, config)
        # モデル側へ反映
        config.meta.version_id = version_id
        now_ms = int(time.time() * 1000)
        if config.meta.created_at is None:
            config.meta.created_at = now_ms
        config.meta.updated_at = now_ms  # updated_at を常に更新

        # metadata_json を更新
        attributes = dict(config.meta.attributes or {})
        cur.execute(
            "UPDATE canonical_config_versions SET updated_at = ?, metadata_json = ? WHERE id = ?",
            (now_ms, json.dumps(attributes, ensure_ascii=False), version_id),
        )
        conn.commit()  # ここでコミット
    return version_id


def _insert_canonical_snapshot(cur: sqlite3.Cursor, config: CanonicalConfig) -> int:
    now_ms = int(time.time() * 1000)
    meta = config.meta
    created = meta.created_at or now_ms
    updated = meta.updated_at or now_ms

    attributes = dict(meta.attributes or {})
    attributes.setdefault("counts", _build_counts(config))
    meta.attributes = attributes

    cur.execute(
        """
        INSERT INTO canonical_config_versions(
            name, schema_version, version_tag, status, description,
            source_config_id, metadata_json, created_at, updated_at, parent_version_id, is_deleted
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            meta.name,
            meta.schema_version,
            meta.version_tag,
            meta.status,
            meta.description,
            meta.source_config_id,
            json.dumps(attributes, ensure_ascii=False),
            created,
            updated,
            meta.parent_version_id,
            meta.is_deleted,
        ),
    )
    version_id = int(cur.lastrowid)

    _insert_items(cur, version_id, config)
    _insert_nodes(cur, version_id, config)
    _insert_arcs(cur, version_id, config)
    _insert_boms(cur, version_id, config)
    _insert_demands(cur, version_id, config)
    _insert_capacities(cur, version_id, config)
    _insert_hierarchies(cur, version_id, config)
    _insert_calendars(cur, version_id, config)

    return version_id


def _insert_items(
    cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig
) -> None:
    if not config.items:
        return
    rows = [
        (
            version_id,
            item.code,
            item.name,
            item.item_type,
            item.uom,
            item.lead_time_days,
            item.lot_size,
            item.min_order_qty,
            item.safety_stock,
            item.unit_cost,
            json.dumps(item.attributes or {}, ensure_ascii=False),
        )
        for item in config.items
    ]
    cur.executemany(
        """
        INSERT INTO canonical_items(
            config_version_id, item_code, item_name, item_type, uom,
            lead_time_days, lot_size, min_order_qty, safety_stock, unit_cost,
            attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_nodes(
    cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig
) -> None:
    if not config.nodes:
        return
    node_rows = []
    inv_rows = []
    prod_rows = []
    for node in config.nodes:
        node_rows.append(
            (
                version_id,
                node.code,
                node.name,
                node.node_type,
                node.timezone,
                node.region,
                node.service_level,
                node.lead_time_days,
                node.storage_capacity,
                1 if node.allow_storage_over_capacity else 0,
                node.storage_cost_fixed,
                node.storage_over_capacity_fixed_cost,
                node.storage_over_capacity_variable_cost,
                node.review_period_days,
                json.dumps(node.attributes or {}, ensure_ascii=False),
            )
        )
        for inv in node.inventory_policies:
            inv_rows.append(
                (
                    version_id,
                    node.code,
                    inv.item_code,
                    inv.initial_inventory,
                    inv.reorder_point,
                    inv.order_up_to,
                    inv.min_order_qty,
                    inv.order_multiple,
                    inv.safety_stock,
                    inv.storage_cost,
                    inv.stockout_cost,
                    inv.backorder_cost,
                    inv.lead_time_days,
                    json.dumps(inv.attributes or {}, ensure_ascii=False),
                )
            )
        for prod in node.production_policies:
            prod_rows.append(
                (
                    version_id,
                    node.code,
                    prod.item_code,
                    prod.production_capacity,
                    1 if prod.allow_over_capacity else 0,
                    prod.over_capacity_fixed_cost,
                    prod.over_capacity_variable_cost,
                    prod.production_cost_fixed,
                    prod.production_cost_variable,
                    json.dumps(prod.attributes or {}, ensure_ascii=False),
                )
            )

    cur.executemany(
        """
        INSERT INTO canonical_nodes(
            config_version_id, node_code, node_name, node_type, timezone,
            region, service_level, lead_time_days, storage_capacity,
            allow_storage_over_capacity, storage_cost_fixed,
            storage_over_capacity_fixed_cost,
            storage_over_capacity_variable_cost, review_period_days,
            attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        node_rows,
    )

    if inv_rows:
        cur.executemany(
            """
            INSERT INTO canonical_node_items(
                config_version_id, node_code, item_code, initial_inventory,
                reorder_point, order_up_to, min_order_qty, order_multiple,
                safety_stock, storage_cost, stockout_cost, backorder_cost,
                lead_time_days, attributes_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            inv_rows,
        )

    if prod_rows:
        cur.executemany(
            """
            INSERT INTO canonical_node_production(
                config_version_id, node_code, item_code, production_capacity,
                allow_over_capacity, over_capacity_fixed_cost,
                over_capacity_variable_cost, production_cost_fixed,
                production_cost_variable, attributes_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            prod_rows,
        )


def _insert_arcs(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    if not config.arcs:
        return
    rows = [
        (
            version_id,
            arc.from_node,
            arc.to_node,
            arc.arc_type,
            arc.lead_time_days,
            arc.capacity_per_day,
            1 if arc.allow_over_capacity else 0,
            arc.transportation_cost_fixed,
            arc.transportation_cost_variable,
            json.dumps(arc.min_order_qty or {}, ensure_ascii=False),
            json.dumps(arc.order_multiple or {}, ensure_ascii=False),
            json.dumps(arc.attributes or {}, ensure_ascii=False),
        )
        for arc in config.arcs
    ]
    cur.executemany(
        """
        INSERT INTO canonical_arcs(
            config_version_id, from_node, to_node, arc_type, lead_time_days,
            capacity_per_day, allow_over_capacity, transportation_cost_fixed,
            transportation_cost_variable, min_order_json, order_multiple_json,
            attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_boms(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    if not config.bom:
        return
    rows = [
        (
            version_id,
            row.parent_item,
            row.child_item,
            row.quantity,
            row.scrap_rate,
            json.dumps(row.attributes or {}, ensure_ascii=False),
        )
        for row in config.bom
    ]
    cur.executemany(
        """
        INSERT INTO canonical_boms(
            config_version_id, parent_item, child_item, quantity, scrap_rate,
            attributes_json
        ) VALUES(?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_demands(
    cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig
) -> None:
    if not config.demands:
        return
    rows = [
        (
            version_id,
            row.node_code,
            row.item_code,
            row.bucket,
            row.demand_model,
            row.mean,
            row.std_dev,
            row.min_qty,
            row.max_qty,
            json.dumps(row.attributes or {}, ensure_ascii=False),
        )
        for row in config.demands
    ]
    cur.executemany(
        """
        INSERT INTO canonical_demands(
            config_version_id, node_code, item_code, bucket, demand_model,
            mean, std_dev, min_qty, max_qty, attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_capacities(
    cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig
) -> None:
    if not config.capacities:
        return
    rows = [
        (
            version_id,
            row.resource_code,
            row.resource_type,
            row.bucket,
            row.capacity,
            row.calendar_code,
            json.dumps(row.attributes or {}, ensure_ascii=False),
        )
        for row in config.capacities
    ]
    cur.executemany(
        """
        INSERT INTO canonical_capacities(
            config_version_id, resource_code, resource_type, bucket, capacity,
            calendar_code, attributes_json
        ) VALUES(?,?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_hierarchies(
    cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig
) -> None:
    if not config.hierarchies:
        return
    rows = [
        (
            version_id,
            row.hierarchy_type,
            row.node_key,
            row.parent_key,
            row.level,
            row.sort_order,
            json.dumps(row.attributes or {}, ensure_ascii=False),
        )
        for row in config.hierarchies
    ]
    cur.executemany(
        """
        INSERT INTO canonical_hierarchies(
            config_version_id, hierarchy_type, node_key, parent_key, level,
            sort_order, attributes_json
        ) VALUES(?,?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_calendars(
    cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig
) -> None:
    if not config.calendars:
        return
    rows = [
        (
            version_id,
            row.calendar_code,
            row.timezone,
            json.dumps(row.definition or {}, ensure_ascii=False),
            json.dumps(row.attributes or {}, ensure_ascii=False),
        )
        for row in config.calendars
    ]
    cur.executemany(
        """
        INSERT INTO canonical_calendars(
            config_version_id, calendar_code, timezone, definition_json,
            attributes_json
        ) VALUES(?,?,?,?,?)
        """,
        rows,
    )


def delete_canonical_config(version_id: int, *, db_path: Optional[str] = None) -> None:
    """指定されたversion_idのCanonical設定を論理削除する。"""
    path = _resolve_db_path(db_path)
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        cur.execute(
            "UPDATE canonical_config_versions SET is_deleted = 1, updated_at = ? WHERE id = ?",
            (int(time.time() * 1000), version_id),
        )
        conn.commit()


__all__ = [
    "CanonicalConfigNotFoundError",
    "list_canonical_versions",
    "list_canonical_version_summaries",
    "get_canonical_config",
    "load_canonical_config_from_db",
    "save_canonical_config",
    "delete_canonical_config",
    "CanonicalVersionSummary",
    "create_planning_input_set",
    "update_planning_input_set",
    "get_planning_input_set",
    "list_planning_input_sets",
    "list_planning_input_set_events",
    "log_planning_input_set_event",
    "delete_planning_input_set",
    "PlanningInputSetSummary",
    "PlanningInputSetNotFoundError",
    "PlanningInputSetConflictError",
]


def _resolve_db_path(db_path: Optional[str]) -> str:
    import os
    from app.db import _DEFAULT_DB, _current_db_path  # ここで遅延インポート

    if _current_db_path:
        return _current_db_path
    env_db_path = os.getenv("SCPLN_DB")
    if env_db_path:
        return env_db_path
    if db_path:
        return db_path
    return str(_DEFAULT_DB)


def _collect_counts(
    version_ids: Iterable[int], db_path: str
) -> Dict[int, Dict[str, int]]:
    ids = [vid for vid in version_ids if vid is not None]
    if not ids:
        return {}
    placeholders = ",".join(["?"] * len(ids))
    tables = {
        "items": "canonical_items",
        "nodes": "canonical_nodes",
        "arcs": "canonical_arcs",
        "bom": "canonical_boms",
        "demands": "canonical_demands",
        "capacities": "canonical_capacities",
        "calendars": "canonical_calendars",
        "hierarchies": "canonical_hierarchies",
    }
    counts: Dict[int, Dict[str, int]] = {
        vid: {key: 0 for key in tables.keys()} for vid in ids
    }
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        for key, table in tables.items():
            rows = cur.execute(
                f"SELECT config_version_id, COUNT(*) AS cnt FROM {table} "
                f"WHERE config_version_id IN ({placeholders}) GROUP BY config_version_id",
                ids,
            ).fetchall()
            for row in rows:
                counts[row["config_version_id"]][key] = row["cnt"]
    return counts


def _is_valid_counts(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    expected = set(_default_counts().keys())
    return expected.issubset(value.keys())


def _default_counts() -> Dict[str, int]:
    return {
        "items": 0,
        "nodes": 0,
        "arcs": 0,
        "bom": 0,
        "demands": 0,
        "capacities": 0,
        "calendars": 0,
        "hierarchies": 0,
    }


def _build_counts(config: CanonicalConfig) -> Dict[str, int]:
    return {
        "items": len(config.items),
        "nodes": len(config.nodes),
        "arcs": len(config.arcs),
        "bom": len(config.bom),
        "demands": len(config.demands),
        "capacities": len(config.capacities),
        "calendars": len(config.calendars),
        "hierarchies": len(config.hierarchies),
    }


def _update_counts_metadata(
    db_path: str,
    metas: Iterable[ConfigMeta],
    counts_map: Dict[int, Dict[str, int]],
) -> None:
    if not counts_map:
        return
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        for meta in metas:
            vid = meta.version_id
            if vid is None or vid not in counts_map:
                continue
            attributes = dict(meta.attributes or {})
            attributes["counts"] = counts_map[vid]
            cur.execute(
                "UPDATE canonical_config_versions SET metadata_json=? WHERE id=?",
                (json.dumps(attributes, ensure_ascii=False), vid),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Planning Input Set CRUD
# ---------------------------------------------------------------------------


def create_planning_input_set(
    *,
    config_version_id: int,
    label: str,
    status: str = "draft",
    source: str = "csv",
    created_by: Optional[str] = None,
    approved_by: Optional[str] = None,
    approved_at: Optional[int] = None,
    review_comment: Optional[str] = None,
    calendar_spec: Optional[PlanningCalendarSpec] = None,
    planning_params: Optional[PlanningParams] = None,
    metadata: Optional[Dict[str, Any]] = None,
    aggregates: Optional[PlanningInputAggregates] = None,
) -> PlanningInputSet:
    now = int(time.time() * 1000)
    aggregates = aggregates or PlanningInputAggregates()
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        try:
            cur.execute(
                """
                INSERT INTO planning_input_sets(
                    config_version_id, label, status, source, created_by,
                    created_at, updated_at, metadata_json, calendar_spec_json,
                    planning_params_json, approved_by, approved_at, review_comment
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    config_version_id,
                    label,
                    status,
                    source,
                    created_by,
                    now,
                    now,
                    _json_dumps(metadata),
                    json.dumps(
                        calendar_spec.model_dump(mode="json")
                        if calendar_spec
                        else {},
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        planning_params.model_dump(mode="json")
                        if planning_params
                        else {},
                        ensure_ascii=False,
                    ),
                    approved_by,
                    approved_at,
                    review_comment,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PlanningInputSetConflictError(str(exc)) from exc

        input_set_id = cur.lastrowid
        _replace_planning_aggregates(cur, input_set_id, aggregates)
        conn.commit()

    return get_planning_input_set(input_set_id=input_set_id, include_aggregates=True)


def update_planning_input_set(
    input_set_id: int,
    *,
    label: Optional[str] = None,
    status: Optional[str] = None,
    approved_by: Any = _UNSET,
    approved_at: Any = _UNSET,
    review_comment: Any = _UNSET,
    calendar_spec: Optional[PlanningCalendarSpec] = None,
    planning_params: Optional[PlanningParams] = None,
    metadata: Optional[Dict[str, Any]] = None,
    aggregates: Optional[PlanningInputAggregates] = None,
    replace_mode: bool = False,
) -> PlanningInputSet:
    fields: List[str] = []
    params: List[Any] = []
    now = int(time.time() * 1000)

    if label is not None:
        fields.append("label = ?")
        params.append(label)
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if approved_by is not _UNSET:
        fields.append("approved_by = ?")
        params.append(approved_by)
    if approved_at is not _UNSET:
        fields.append("approved_at = ?")
        params.append(approved_at)
    if review_comment is not _UNSET:
        fields.append("review_comment = ?")
        params.append(review_comment)
    if metadata is not None:
        fields.append("metadata_json = ?")
        params.append(_json_dumps(metadata))
    if calendar_spec is not None:
        fields.append("calendar_spec_json = ?")
        params.append(
            json.dumps(calendar_spec.model_dump(mode="json"), ensure_ascii=False)
        )
    if planning_params is not None:
        fields.append("planning_params_json = ?")
        params.append(
            json.dumps(planning_params.model_dump(mode="json"), ensure_ascii=False)
        )
    fields.append("updated_at = ?")
    params.append(now)
    params.append(input_set_id)

    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        if fields:
            cur.execute(
                f"""
                UPDATE planning_input_sets
                SET {", ".join(fields)}
                WHERE id = ?
                """,
                params,
            )
            if cur.rowcount == 0:
                raise PlanningInputSetNotFoundError(f"id={input_set_id} not found")

        if aggregates is not None:
            if replace_mode:
                _replace_planning_aggregates(cur, input_set_id, aggregates)
            else:
                # replace_mode=False の場合も現状全削除→再挿入で差分管理を簡易化
                _replace_planning_aggregates(cur, input_set_id, aggregates)

        conn.commit()

    return get_planning_input_set(input_set_id=input_set_id, include_aggregates=True)


def get_planning_input_set(
    *,
    input_set_id: Optional[int] = None,
    label: Optional[str] = None,
    config_version_id: Optional[int] = None,
    status: Optional[str] = None,
    include_aggregates: bool = True,
) -> PlanningInputSet:
    conditions: List[str] = []
    params: List[Any] = []
    if input_set_id is not None:
        conditions.append("id = ?")
        params.append(input_set_id)
    if label is not None:
        conditions.append("label = ?")
        params.append(label)
    if config_version_id is not None:
        conditions.append("config_version_id = ?")
        params.append(config_version_id)
    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    if not conditions:
        raise ValueError("input_set_id, label, or config_version_id must be specified")

    query = "SELECT * FROM planning_input_sets WHERE " + " AND ".join(conditions)
    query += " ORDER BY updated_at DESC LIMIT 1"

    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        row = cur.execute(query, params).fetchone()
        if not row:
            raise PlanningInputSetNotFoundError("Planning input set not found")
        aggregates = (
            _load_planning_input_aggregates(cur, row["id"])
            if include_aggregates
            else PlanningInputAggregates()
        )
        return _row_to_planning_input_set(row, aggregates)


def list_planning_input_sets(
    *,
    config_version_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> List[PlanningInputSetSummary]:
    conditions: List[str] = []
    params: List[Any] = []
    if config_version_id is not None:
        conditions.append("config_version_id = ?")
        params.append(config_version_id)
    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    query = (
        "SELECT id, config_version_id, label, status, source, created_at, updated_at, "
        "approved_by, approved_at, review_comment "
        "FROM planning_input_sets WHERE "
        + where_clause
        + " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])

    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        rows = cur.execute(query, params).fetchall()
        return [
            PlanningInputSetSummary(
                id=row["id"],
                config_version_id=row["config_version_id"],
                label=row["label"],
                status=row["status"],
                source=row["source"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                approved_by=row["approved_by"],
                approved_at=row["approved_at"],
                review_comment=row["review_comment"],
            )
            for row in rows
        ]


def list_planning_input_set_events(
    input_set_id: int, *, limit: int = 100
) -> List[PlanningInputSetEvent]:
    query = (
        "SELECT id, input_set_id, action, actor, comment, metadata_json, created_at "
        "FROM planning_input_set_events "
        "WHERE input_set_id = ? "
        "ORDER BY created_at DESC "
        "LIMIT ?"
    )
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        rows = cur.execute(query, (input_set_id, limit)).fetchall()
        return [_row_to_planning_input_set_event(row) for row in rows]


def log_planning_input_set_event(
    input_set_id: int,
    *,
    action: str,
    actor: Optional[str] = None,
    comment: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> PlanningInputSetEvent:
    now = int(time.time() * 1000)
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO planning_input_set_events(
                input_set_id, action, actor, comment, metadata_json, created_at
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                input_set_id,
                action,
                actor,
                comment,
                _json_dumps(metadata),
                now,
            ),
        )
        event_id = cur.lastrowid
        conn.commit()
        return PlanningInputSetEvent(
            id=event_id,
            input_set_id=input_set_id,
            action=action,
            actor=actor,
            comment=comment,
            metadata=metadata or {},
            created_at=now,
        )


def delete_planning_input_set(
    input_set_id: int, *, hard: bool = False
) -> None:
    with closing(_conn()) as conn, closing(conn.cursor()) as cur:
        if hard:
            cur.execute("DELETE FROM planning_input_sets WHERE id = ?", (input_set_id,))
        else:
            cur.execute(
                """
                UPDATE planning_input_sets
                SET status = 'archived', updated_at = ?
                WHERE id = ?
                """,
                (int(time.time() * 1000), input_set_id),
            )
        if cur.rowcount == 0:
            raise PlanningInputSetNotFoundError(f"id={input_set_id} not found")
        conn.commit()
