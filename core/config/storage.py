"""Canonical設定の永続化レイヤー。"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import Any, Dict, Iterable, List, Optional

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
)
from .validators import ValidationResult, validate_canonical_config


class CanonicalConfigNotFoundError(RuntimeError):
    """指定したIDのCanonical設定が見つからない場合に送出。"""


def list_canonical_versions(
    *, limit: int = 50, db_path: Optional[str] = None
) -> List[ConfigMeta]:
    """保存済みCanonical設定のメタ情報を取得する。"""

    path = _resolve_db_path(db_path)
    with closing(_connect(path)) as conn, closing(conn.cursor()) as cur:
        rows = cur.execute(
            """
            SELECT id, name, schema_version, version_tag, status, description,
                   source_config_id, metadata_json, created_at, updated_at
            FROM canonical_config_versions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    metas: List[ConfigMeta] = []
    for row in rows:
        metas.append(_row_to_meta(row))
    return metas


def get_canonical_config(
    version_id: int, *, db_path: Optional[str] = None
) -> CanonicalConfig:
    """指定IDのCanonical設定を復元する。"""

    path = _resolve_db_path(db_path)
    with closing(_connect(path)) as conn, closing(conn.cursor()) as cur:
        meta_row = cur.execute(
            """
            SELECT id, name, schema_version, version_tag, status, description,
                   source_config_id, metadata_json, created_at, updated_at
            FROM canonical_config_versions
            WHERE id=?
            """,
            (version_id,),
        ).fetchone()
        if not meta_row:
            raise CanonicalConfigNotFoundError(f"config version id={version_id} not found")

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
    demands = [_row_to_demand(row) for row in demand_rows]
    capacities = [_row_to_capacity(row) for row in capacity_rows]
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


# --- 内部ユーティリティ ---


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_json(text: Optional[str], default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _to_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except Exception:
        return default


def _row_to_meta(row: sqlite3.Row) -> ConfigMeta:
    return ConfigMeta(
        version_id=row["id"],
        name=row["name"],
        schema_version=row["schema_version"],
        version_tag=row["version_tag"],
        status=row["status"],
        description=row["description"],
        source_config_id=row["source_config_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        attributes=_parse_json(row["metadata_json"], {}),
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
        attributes=_parse_json(row["attributes_json"], {}),
    )


def _group_inventory(rows: Iterable[sqlite3.Row]) -> Dict[str, List[NodeInventoryPolicy]]:
    inventory: Dict[str, List[NodeInventoryPolicy]] = defaultdict(list)
    for row in rows:
        policy = NodeInventoryPolicy(
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
            attributes=_parse_json(row["attributes_json"], {}),
        )
        inventory[row["node_code"]].append(policy)
    return inventory


def _group_production(rows: Iterable[sqlite3.Row]) -> Dict[str, List[NodeProductionPolicy]]:
    production: Dict[str, List[NodeProductionPolicy]] = defaultdict(list)
    for row in rows:
        policy = NodeProductionPolicy(
            item_code=row["item_code"],
            production_capacity=row["production_capacity"],
            allow_over_capacity=_to_bool(row["allow_over_capacity"], default=True),
            over_capacity_fixed_cost=row["over_capacity_fixed_cost"],
            over_capacity_variable_cost=row["over_capacity_variable_cost"],
            production_cost_fixed=row["production_cost_fixed"],
            production_cost_variable=row["production_cost_variable"],
            attributes=_parse_json(row["attributes_json"], {}),
        )
        production[row["node_code"]].append(policy)
    return production


def _row_to_node(
    row: sqlite3.Row,
    inventory_map: Dict[str, List[NodeInventoryPolicy]],
    production_map: Dict[str, List[NodeProductionPolicy]],
) -> CanonicalNode:
    code = row["node_code"]
    return CanonicalNode(
        code=code,
        name=row["node_name"],
        node_type=row["node_type"],
        timezone=row["timezone"],
        region=row["region"],
        service_level=row["service_level"],
        lead_time_days=row["lead_time_days"],
        storage_capacity=row["storage_capacity"],
        allow_storage_over_capacity=_to_bool(row["allow_storage_over_capacity"], default=True),
        storage_cost_fixed=row["storage_cost_fixed"],
        storage_over_capacity_fixed_cost=row["storage_over_capacity_fixed_cost"],
        storage_over_capacity_variable_cost=row["storage_over_capacity_variable_cost"],
        review_period_days=row["review_period_days"],
        inventory_policies=inventory_map.get(code, []),
        production_policies=production_map.get(code, []),
        attributes=_parse_json(row["attributes_json"], {}),
    )


def _row_to_arc(row: sqlite3.Row) -> CanonicalArc:
    return CanonicalArc(
        from_node=row["from_node"],
        to_node=row["to_node"],
        arc_type=row["arc_type"],
        lead_time_days=row["lead_time_days"],
        capacity_per_day=row["capacity_per_day"],
        allow_over_capacity=_to_bool(row["allow_over_capacity"], default=True),
        transportation_cost_fixed=row["transportation_cost_fixed"],
        transportation_cost_variable=row["transportation_cost_variable"],
        min_order_qty=_parse_json(row["min_order_json"], {}),
        order_multiple=_parse_json(row["order_multiple_json"], {}),
        attributes=_parse_json(row["attributes_json"], {}),
    )


def _row_to_bom(row: sqlite3.Row) -> CanonicalBom:
    return CanonicalBom(
        parent_item=row["parent_item"],
        child_item=row["child_item"],
        quantity=row["quantity"],
        scrap_rate=row["scrap_rate"],
        attributes=_parse_json(row["attributes_json"], {}),
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
        attributes=_parse_json(row["attributes_json"], {}),
    )


def _row_to_capacity(row: sqlite3.Row) -> CapacityProfile:
    return CapacityProfile(
        resource_code=row["resource_code"],
        resource_type=row["resource_type"],
        bucket=row["bucket"],
        capacity=row["capacity"],
        calendar_code=row["calendar_code"],
        attributes=_parse_json(row["attributes_json"], {}),
    )


def _row_to_hierarchy(row: sqlite3.Row) -> HierarchyEntry:
    return HierarchyEntry(
        hierarchy_type=row["hierarchy_type"],
        node_key=row["node_key"],
        parent_key=row["parent_key"],
        level=row["level"],
        sort_order=row["sort_order"],
        attributes=_parse_json(row["attributes_json"], {}),
    )


def _row_to_calendar(row: sqlite3.Row) -> CalendarDefinition:
    return CalendarDefinition(
        calendar_code=row["calendar_code"],
        timezone=row["timezone"],
        definition=_parse_json(row["definition_json"], {}),
        attributes=_parse_json(row["attributes_json"], {}),
    )


__all__ = [
    "CanonicalConfigNotFoundError",
    "list_canonical_versions",
    "get_canonical_config",
    "load_canonical_config_from_db",
]
def _resolve_db_path(db_path: Optional[str]) -> str:
    if db_path:
        return db_path
    from app.db import DB_PATH  # lazy import to avoid circular dependency

    return DB_PATH

