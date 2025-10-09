"""レガシー設定ソースからCanonical設定を生成するローダー。"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


class CanonicalLoaderError(RuntimeError):
    """ローダー処理における例外。"""


def load_canonical_config(
    *,
    name: str,
    psi_input_path: Path,
    planning_dir: Path,
    product_hierarchy_path: Optional[Path] = None,
    location_hierarchy_path: Optional[Path] = None,
    include_validation: bool = True,
) -> Tuple[CanonicalConfig, Optional[ValidationResult]]:
    """レガシーJSON/CSVソースからCanonical設定を構築する。"""

    psi_data = _read_json(psi_input_path)
    planning_payload = _read_planning_dir(planning_dir)
    hier_product = _read_json(product_hierarchy_path) if product_hierarchy_path else {}
    hier_location = (
        _read_json(location_hierarchy_path) if location_hierarchy_path else {}
    )

    item_records: Dict[str, Dict] = {}
    node_records: Dict[str, Dict] = {}
    bom_pairs: Dict[Tuple[str, str], Dict] = {}

    _ingest_psi_products(psi_data, item_records, bom_pairs)
    _ingest_psi_nodes(psi_data, item_records, node_records)
    arcs = _ingest_psi_arcs(psi_data)
    demands = _ingest_psi_demands(psi_data)

    _ingest_planning_items(planning_payload, item_records)
    _ingest_planning_inventory(planning_payload, node_records)
    _ingest_planning_bom(planning_payload, bom_pairs)
    capacities = _ingest_planning_capacity(planning_payload)

    hierarchies = _build_hierarchies(hier_product, hier_location)

    items = [_build_item(data) for data in item_records.values()]
    nodes = [_build_node(data) for data in node_records.values()]
    bom = [_build_bom(data) for data in bom_pairs.values()]

    calendars = _build_calendars(planning_payload)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    meta = ConfigMeta(
        name=name,
        schema_version="canonical-1.0",
        status="draft",
        created_at=now_ms,
        updated_at=now_ms,
        attributes={
            "sources": {
                "psi_input": str(psi_input_path),
                "planning_dir": str(planning_dir),
                "product_hierarchy": (
                    str(product_hierarchy_path) if product_hierarchy_path else None
                ),
                "location_hierarchy": (
                    str(location_hierarchy_path) if location_hierarchy_path else None
                ),
            },
            "planning_payload": planning_payload,
        },
    )

    config = CanonicalConfig(
        meta=meta,
        items=sorted(items, key=lambda x: x.code),
        nodes=sorted(nodes, key=lambda x: x.code),
        arcs=sorted(arcs, key=lambda x: (x.from_node, x.to_node, x.arc_type)),
        bom=sorted(bom, key=lambda x: (x.parent_item, x.child_item)),
        demands=sorted(demands, key=lambda x: (x.node_code, x.item_code, x.bucket)),
        capacities=sorted(
            capacities, key=lambda x: (x.resource_type, x.resource_code, x.bucket)
        ),
        calendars=calendars,
        hierarchies=hierarchies,
    )

    validation: Optional[ValidationResult] = None
    if include_validation:
        validation = validate_canonical_config(config)

    return config, validation


def _read_json(path: Path | None) -> Dict:
    if not path:
        return {}
    if not path.exists():
        raise CanonicalLoaderError(f"JSONファイルが見つかりません: {path}")
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        return [dict(row) for row in reader]


def _read_planning_dir(directory: Path) -> Dict[str, List[Dict[str, str]]]:
    if not directory.exists():
        raise CanonicalLoaderError(f"Planningディレクトリが見つかりません: {directory}")
    return {
        "item": _read_csv(directory / "item.csv"),
        "inventory": _read_csv(directory / "inventory.csv"),
        "bom": _read_csv(directory / "bom.csv"),
        "capacity": _read_csv(directory / "capacity.csv"),
        "demand_family": _read_csv(directory / "demand_family.csv"),
        "mix_share": _read_csv(directory / "mix_share.csv"),
        "open_po": _read_csv(directory / "open_po.csv"),
        "period_cost": _read_csv(directory / "period_cost.csv"),
        "period_score": _read_csv(directory / "period_score.csv"),
    }


def _ingest_psi_products(
    psi_data: Dict,
    item_records: Dict[str, Dict],
    bom_pairs: Dict[Tuple[str, str], Dict],
) -> None:
    for prod in psi_data.get("products", []):
        code = prod.get("name")
        if not code:
            continue
        data = item_records.setdefault(
            code,
            {
                "code": code,
                "name": code,
                "item_type": "product",
                "uom": "unit",
                "attributes": {},
            },
        )
        data["name"] = prod.get("name", code)
        data["attributes"].setdefault("sales_price", prod.get("sales_price"))
        for bom_row in prod.get("assembly_bom", []) or []:
            child = bom_row.get("item_name")
            if not child:
                continue
            pair = (code, child)
            bom_pairs.setdefault(
                pair,
                {
                    "parent_item": code,
                    "child_item": child,
                    "quantity": _as_float(bom_row.get("quantity_per"), default=1.0),
                    "scrap_rate": None,
                    "attributes": {},
                },
            )


def _ingest_psi_nodes(
    psi_data: Dict, item_records: Dict[str, Dict], node_records: Dict[str, Dict]
) -> None:
    for raw in psi_data.get("nodes", []) or []:
        code = raw.get("name")
        if not code:
            continue
        node = node_records.setdefault(
            code,
            {
                "code": code,
                "name": raw.get("name", code),
                "node_type": _map_node_type(raw.get("node_type")),
                "lead_time_days": _as_int(raw.get("lead_time"), default=0),
                "service_level": _as_float(raw.get("service_level")),
                "storage_capacity": _as_float(raw.get("storage_capacity")),
                "allow_storage_over_capacity": bool(
                    raw.get("allow_storage_over_capacity", True)
                ),
                "storage_cost_fixed": _as_float(raw.get("storage_cost_fixed")),
                "storage_over_capacity_fixed_cost": _as_float(
                    raw.get("storage_over_capacity_fixed_cost")
                ),
                "storage_over_capacity_variable_cost": _as_float(
                    raw.get("storage_over_capacity_variable_cost")
                ),
                "review_period_days": _as_int(raw.get("review_period_days")),
                "attributes": {},
                "inventory": {},
                "production": {},
            },
        )
        node["attributes"].update(
            {
                "backorder_enabled": raw.get("backorder_enabled"),
                "lost_sales": raw.get("lost_sales"),
                "stockout_cost_per_unit": raw.get("stockout_cost_per_unit"),
                "backorder_cost_per_unit_per_day": raw.get(
                    "backorder_cost_per_unit_per_day"
                ),
                "material_cost": raw.get("material_cost"),
            }
        )

        for item_code, qty in (raw.get("initial_stock") or {}).items():
            item_records.setdefault(
                item_code,
                {
                    "code": item_code,
                    "name": item_code,
                    "item_type": (
                        "material" if node["node_type"] == "material" else "product"
                    ),
                    "uom": "unit",
                    "attributes": {},
                },
            )
            inv = node["inventory"].setdefault(
                item_code,
                {
                    "item_code": item_code,
                    "initial_inventory": 0.0,
                    "reorder_point": None,
                    "order_up_to": None,
                    "min_order_qty": None,
                    "order_multiple": None,
                    "safety_stock": None,
                    "storage_cost": None,
                    "stockout_cost": None,
                    "backorder_cost": None,
                    "lead_time_days": None,
                    "attributes": {},
                },
            )
            inv["initial_inventory"] = _as_float(qty, default=0.0)
            inv["min_order_qty"] = _as_float((raw.get("moq") or {}).get(item_code))
            inv["order_multiple"] = _as_float(
                (raw.get("order_multiple") or {}).get(item_code)
            )
            inv["reorder_point"] = _as_float(
                (raw.get("reorder_point") or {}).get(item_code)
            )
            inv["order_up_to"] = _as_float(
                (raw.get("order_up_to_level") or {}).get(item_code)
            )
            storage_var = (raw.get("storage_cost_variable") or {}).get(item_code)
            inv["storage_cost"] = _as_float(storage_var)
            inv["stockout_cost"] = _as_float(raw.get("stockout_cost_per_unit"))
            inv["backorder_cost"] = _as_float(
                raw.get("backorder_cost_per_unit_per_day")
            )

        if raw.get("node_type") == "factory":
            node["production"]["__any__"] = {
                "item_code": None,
                "production_capacity": _as_float(raw.get("production_capacity")),
                "allow_over_capacity": bool(
                    raw.get("allow_production_over_capacity", True)
                ),
                "over_capacity_fixed_cost": _as_float(
                    raw.get("production_over_capacity_fixed_cost")
                ),
                "over_capacity_variable_cost": _as_float(
                    raw.get("production_over_capacity_variable_cost")
                ),
                "production_cost_fixed": _as_float(raw.get("production_cost_fixed")),
                "production_cost_variable": _as_float(
                    raw.get("production_cost_variable")
                ),
                "attributes": {},
            }


def _ingest_psi_arcs(psi_data: Dict) -> List[CanonicalArc]:
    arcs: List[CanonicalArc] = []
    for raw in psi_data.get("network", []) or []:
        arcs.append(
            CanonicalArc(
                from_node=raw.get("from_node", ""),
                to_node=raw.get("to_node", ""),
                arc_type="transport",
                lead_time_days=_as_int(raw.get("lead_time"), default=0),
                capacity_per_day=_as_float(raw.get("capacity_per_day")),
                allow_over_capacity=bool(raw.get("allow_over_capacity", True)),
                transportation_cost_fixed=_as_float(
                    raw.get("transportation_cost_fixed")
                ),
                transportation_cost_variable=_as_float(
                    raw.get("transportation_cost_variable")
                ),
                min_order_qty={
                    k: _as_float(v) for k, v in (raw.get("moq") or {}).items()
                },
                order_multiple={
                    k: _as_float(v)
                    for k, v in (raw.get("order_multiple") or {}).items()
                },
                attributes={
                    "over_capacity_fixed_cost": _as_float(
                        raw.get("over_capacity_fixed_cost")
                    ),
                    "over_capacity_variable_cost": _as_float(
                        raw.get("over_capacity_variable_cost")
                    ),
                },
            )
        )
    return arcs


def _ingest_psi_demands(psi_data: Dict) -> List[DemandProfile]:
    demands: List[DemandProfile] = []
    for row in psi_data.get("customer_demand", []) or []:
        node = row.get("store_name")
        item = row.get("product_name")
        if not node or not item:
            continue
        std = _as_float(row.get("demand_std_dev"))
        demands.append(
            DemandProfile(
                node_code=node,
                item_code=item,
                bucket="default",
                demand_model="normal" if std and std > 0 else "deterministic",
                mean=_as_float(row.get("demand_mean"), default=0.0),
                std_dev=std,
            )
        )
    return demands


def _ingest_planning_items(
    planning_payload: Dict[str, List[Dict[str, str]]],
    item_records: Dict[str, Dict],
) -> None:
    for row in planning_payload.get("item", []):
        code = row.get("item")
        if not code:
            continue
        data = item_records.setdefault(
            code,
            {
                "code": code,
                "name": code,
                "item_type": "product",
                "uom": "unit",
                "attributes": {},
            },
        )
        data["lead_time_days"] = _as_int(
            row.get("lt"), default=data.get("lead_time_days")
        )
        data["lot_size"] = _as_float(row.get("lot"), default=data.get("lot_size"))
        data["min_order_qty"] = _as_float(
            row.get("moq"), default=data.get("min_order_qty")
        )


def _ingest_planning_inventory(
    planning_payload: Dict[str, List[Dict[str, str]]],
    node_records: Dict[str, Dict],
) -> None:
    for row in planning_payload.get("inventory", []):
        loc = row.get("loc")
        item_code = row.get("item")
        if not loc or not item_code:
            continue
        node = node_records.setdefault(
            loc,
            {
                "code": loc,
                "name": loc,
                "node_type": "warehouse",
                "lead_time_days": 0,
                "service_level": None,
                "storage_capacity": None,
                "allow_storage_over_capacity": True,
                "storage_cost_fixed": None,
                "storage_over_capacity_fixed_cost": None,
                "storage_over_capacity_variable_cost": None,
                "review_period_days": None,
                "attributes": {},
                "inventory": {},
                "production": {},
            },
        )
        inv = node["inventory"].setdefault(
            item_code,
            {
                "item_code": item_code,
                "initial_inventory": 0.0,
                "reorder_point": None,
                "order_up_to": None,
                "min_order_qty": None,
                "order_multiple": None,
                "safety_stock": None,
                "storage_cost": None,
                "stockout_cost": None,
                "backorder_cost": None,
                "lead_time_days": None,
                "attributes": {},
            },
        )
        inv["initial_inventory"] = _as_float(row.get("qty"), default=0.0)


def _ingest_planning_bom(
    planning_payload: Dict[str, List[Dict[str, str]]],
    bom_pairs: Dict[Tuple[str, str], Dict],
) -> None:
    for row in planning_payload.get("bom", []):
        parent = row.get("parent")
        child = row.get("child")
        if not parent or not child:
            continue
        key = (parent, child)
        existing = bom_pairs.get(key)
        if existing:
            existing["quantity"] = existing.get("quantity") or _as_float(
                row.get("qty"), default=1.0
            )
        else:
            bom_pairs[key] = {
                "parent_item": parent,
                "child_item": child,
                "quantity": _as_float(row.get("qty"), default=1.0),
                "scrap_rate": None,
                "attributes": {},
            }


def _ingest_planning_capacity(
    planning_payload: Dict[str, List[Dict[str, str]]],
) -> List[CapacityProfile]:
    capacities: List[CapacityProfile] = []
    for row in planning_payload.get("capacity", []):
        resource = row.get("workcenter")
        period = row.get("period")
        if not resource or not period:
            continue
        capacities.append(
            CapacityProfile(
                resource_code=resource,
                resource_type="workcenter",
                bucket=period,
                capacity=_as_float(row.get("capacity"), default=0.0),
            )
        )
    return capacities


def _build_hierarchies(
    product_hierarchy: Dict, location_hierarchy: Dict
) -> List[HierarchyEntry]:
    entries: List[HierarchyEntry] = []
    for key, payload in (product_hierarchy or {}).items():
        entries.append(
            HierarchyEntry(
                hierarchy_type="product",
                node_key=str(key),
                parent_key=None,
                level=payload.get("category"),
                attributes={
                    k: v
                    for k, v in payload.items()
                    if k not in {"item", "category", "department"}
                },
            )
        )
    for key, payload in (location_hierarchy or {}).items():
        entries.append(
            HierarchyEntry(
                hierarchy_type="location",
                node_key=str(key),
                parent_key=None,
                level=payload.get("region"),
                attributes={
                    k: v for k, v in payload.items() if k not in {"region", "country"}
                },
            )
        )
    return entries


def _build_calendars(
    payload: Dict[str, List[Dict[str, str]]],
) -> List[CalendarDefinition]:
    if not payload.get("period_cost") and not payload.get("period_score"):
        return []
    definition = {
        "period_cost": payload.get("period_cost", []),
        "period_score": payload.get("period_score", []),
    }
    return [
        CalendarDefinition(
            calendar_code="PLANNING_PERIODS",
            definition=definition,
            attributes={},
        )
    ]


def _build_item(data: Dict) -> CanonicalItem:
    return CanonicalItem(
        **{k: v for k, v in data.items() if k in CanonicalItem.model_fields}
    )


def _build_node(data: Dict) -> CanonicalNode:
    inventory = [
        NodeInventoryPolicy(**inv) for inv in data.get("inventory", {}).values()
    ]
    production = [
        NodeProductionPolicy(**policy) for policy in data.get("production", {}).values()
    ]
    node_kwargs = {k: v for k, v in data.items() if k in CanonicalNode.model_fields}
    node_kwargs["inventory_policies"] = inventory
    node_kwargs["production_policies"] = production
    return CanonicalNode(**node_kwargs)


def _build_bom(data: Dict) -> CanonicalBom:
    return CanonicalBom(
        **{k: v for k, v in data.items() if k in CanonicalBom.model_fields}
    )


def _map_node_type(raw_type: Optional[str]) -> str:
    if not raw_type:
        return "warehouse"
    if raw_type == "material":
        return "material"
    if raw_type in {"store", "warehouse", "factory", "supplier"}:
        return raw_type
    return "warehouse"


def _as_float(value, *, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, *, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "CanonicalLoaderError",
    "load_canonical_config",
]
