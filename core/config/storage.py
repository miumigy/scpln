"""Canonical設定の永続化レイヤー。"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
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


@dataclass
class CanonicalVersionSummary:
    """Canonical設定のメタ情報と件数サマリ。"""

    meta: ConfigMeta
    counts: Dict[str, int]


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


def list_canonical_version_summaries(
    *, limit: int = 50, db_path: Optional[str] = None
) -> List[CanonicalVersionSummary]:
    """メタ情報に加えて主要テーブル件数を含むサマリを取得する。"""

    metas = list_canonical_versions(limit=limit, db_path=db_path)
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


def save_canonical_config(
    config: CanonicalConfig,
    *,
    db_path: Optional[str] = None,
) -> int:
    """Canonical設定をDBへ保存し、新しいversion_idを返す。"""

    path = _resolve_db_path(db_path)
    with closing(_connect(path)) as conn, closing(conn.cursor()) as cur:
        conn.execute("PRAGMA foreign_keys=ON")
        version_id = _insert_canonical_snapshot(cur, config)
        conn.commit()
    # モデル側へ反映
    config.meta.version_id = version_id
    now_ms = int(time.time() * 1000)
    if config.meta.created_at is None:
        config.meta.created_at = now_ms
    if config.meta.updated_at is None:
        config.meta.updated_at = now_ms
    return version_id


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


def _group_inventory(
    rows: Iterable[sqlite3.Row],
) -> Dict[str, List[NodeInventoryPolicy]]:
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


def _group_production(
    rows: Iterable[sqlite3.Row],
) -> Dict[str, List[NodeProductionPolicy]]:
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
        allow_storage_over_capacity=_to_bool(
            row["allow_storage_over_capacity"], default=True
        ),
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
            source_config_id, metadata_json, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
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


__all__ = [
    "CanonicalConfigNotFoundError",
    "list_canonical_versions",
    "list_canonical_version_summaries",
    "get_canonical_config",
    "load_canonical_config_from_db",
    "save_canonical_config",
    "CanonicalVersionSummary",
]


def _resolve_db_path(db_path: Optional[str]) -> str:
    from app.db import _DEFAULT_DB, _current_db_path  # lazy import to avoid circular dependency

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
    with closing(_connect(db_path)) as conn, closing(conn.cursor()) as cur:
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
    with closing(_connect(db_path)) as conn, closing(conn.cursor()) as cur:
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
