"""Canonical設定から各種アプリ入力を生成するビルダー。"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from domain.models import (
    BomItem,
    CustomerDemand,
    FactoryNode,
    MaterialNode,
    NetworkLink,
    Product,
    SimulationInput,
    StoreNode,
    WarehouseNode,
)
from planning.schemas import (
    AggregatePlanInput,
    CapacityRecord,
    FamilyDemandRecord,
    InventoryRecord,
    ItemMasterRecord,
    MixShareRecord,
    OpenPORecord,
)

from .models import (
    CanonicalArc,
    CanonicalBom,
    CanonicalConfig,
    CanonicalItem,
    CanonicalNode,
    DemandProfile,
)


DEFAULT_PLANNING_HORIZON = 100


@dataclass
class PlanningDataBundle:
    """Planningパイプライン向けデータ一式。"""

    aggregate_input: AggregatePlanInput
    period_cost: List[Dict[str, Any]] = field(default_factory=list)
    period_score: List[Dict[str, Any]] = field(default_factory=list)


def build_simulation_input(
    config: CanonicalConfig,
    *,
    planning_horizon: Optional[int] = None,
    random_seed: Optional[int] = None,
) -> SimulationInput:
    """Canonical設定からPSIシミュレーション入力を構築する。"""

    horizon = _resolve_planning_horizon(config, planning_horizon)
    items_by_code = {item.code: item for item in config.items}
    products = _build_products(config.items, config.bom)
    nodes = [_build_node(node, items_by_code) for node in config.nodes]
    network = [_build_network_link(arc) for arc in config.arcs]
    demands = [_build_customer_demand(row) for row in config.demands]

    return SimulationInput(
        schema_version=config.meta.schema_version or "1.0",
        planning_horizon=horizon,
        products=products,
        nodes=nodes,
        network=network,
        customer_demand=demands,
        random_seed=random_seed,
    )


def build_planning_inputs(config: CanonicalConfig) -> PlanningDataBundle:
    """Canonical設定からPlanning Hub向け入力を生成する。"""

    payload = (config.meta.attributes or {}).get("planning_payload") or {}
    if payload:
        aggregate = AggregatePlanInput(
            demand_family=_convert_demand_family(payload.get("demand_family")),
            capacity=_convert_capacity(payload.get("capacity")),
            mix_share=_convert_mix_share(payload.get("mix_share")),
            item_master=_convert_item_master(payload.get("item")),
            inventory=_convert_inventory(payload.get("inventory")),
            open_po=_convert_open_po(payload.get("open_po")),
        )
        period_cost = _normalize_period_entries(
            payload.get("period_cost"), value_key="cost"
        )
        period_score = _normalize_period_entries(
            payload.get("period_score"), value_key="score"
        )
        return PlanningDataBundle(
            aggregate_input=aggregate,
            period_cost=period_cost,
            period_score=period_score,
        )

    # Fallback: Canonical構造から最小限のPlanning入力を組み立てる
    return _build_planning_bundle_from_canonical(config)


def _resolve_planning_horizon(config: CanonicalConfig, override: Optional[int]) -> int:
    if override is not None:
        return max(1, int(override))
    attr = (config.meta.attributes or {}).get("planning_horizon")
    if attr is not None:
        try:
            value = int(attr)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return DEFAULT_PLANNING_HORIZON


def _build_products(
    items: Iterable[CanonicalItem], bom_rows: Iterable[CanonicalBom]
) -> List[Product]:
    bom_map: Dict[str, List[BomItem]] = defaultdict(list)
    for row in bom_rows:
        bom_map[row.parent_item].append(
            BomItem(item_name=row.child_item, quantity_per=row.quantity)
        )

    products: List[Product] = []
    for item in items:
        if item.item_type != "product":
            continue
        sales_price = _to_float(item.attributes.get("sales_price"))
        products.append(
            Product(
                name=item.code,
                sales_price=sales_price,
                assembly_bom=bom_map.get(item.code, []),
            )
        )
    return products


def _build_node(node: CanonicalNode, items_by_code: Dict[str, CanonicalItem]):
    initial_stock: Dict[str, float] = {}
    moq_map: Dict[str, float] = {}
    order_multiple_map: Dict[str, float] = {}
    storage_cost_variable: Dict[str, float] = {}
    reorder_point: Dict[str, float] = {}
    order_up_to: Dict[str, float] = {}
    stockout_cost = _to_float(node.attributes.get("stockout_cost_per_unit"))
    backorder_cost = _to_float(node.attributes.get("backorder_cost_per_unit_per_day"))

    for policy in node.inventory_policies:
        initial_stock[policy.item_code] = policy.initial_inventory or 0.0
        if policy.min_order_qty is not None:
            moq_map[policy.item_code] = float(policy.min_order_qty)
        if policy.order_multiple is not None:
            order_multiple_map[policy.item_code] = float(policy.order_multiple)
        if policy.storage_cost is not None:
            storage_cost_variable[policy.item_code] = float(policy.storage_cost)
        if policy.reorder_point is not None:
            reorder_point[policy.item_code] = float(policy.reorder_point)
        if policy.order_up_to is not None:
            order_up_to[policy.item_code] = float(policy.order_up_to)

    storage_capacity = node.storage_capacity or sys.float_info.max
    storage_cost_fixed = _to_float(node.storage_cost_fixed)
    storage_over_fixed = _to_float(node.storage_over_capacity_fixed_cost)
    storage_over_variable = _to_float(node.storage_over_capacity_variable_cost)
    backorder_enabled = bool(node.attributes.get("backorder_enabled", True))
    lost_sales = bool(node.attributes.get("lost_sales", False))
    review_period = node.review_period_days or 0
    service_level = node.service_level if node.service_level is not None else 0.95

    if node.node_type == "store":
        return StoreNode(
            name=node.code,
            initial_stock=initial_stock,
            lead_time=node.lead_time_days or 0,
            storage_cost_fixed=storage_cost_fixed,
            storage_cost_variable=storage_cost_variable,
            backorder_enabled=backorder_enabled,
            lost_sales=lost_sales,
            review_period_days=review_period,
            stockout_cost_per_unit=stockout_cost,
            backorder_cost_per_unit_per_day=backorder_cost,
            storage_capacity=storage_capacity,
            allow_storage_over_capacity=node.allow_storage_over_capacity,
            storage_over_capacity_fixed_cost=storage_over_fixed,
            storage_over_capacity_variable_cost=storage_over_variable,
            service_level=service_level,
            moq=moq_map,
            order_multiple=order_multiple_map,
        )

    if node.node_type == "warehouse":
        return WarehouseNode(
            name=node.code,
            initial_stock=initial_stock,
            lead_time=node.lead_time_days or 0,
            storage_cost_fixed=storage_cost_fixed,
            storage_cost_variable=storage_cost_variable,
            backorder_enabled=backorder_enabled,
            lost_sales=lost_sales,
            review_period_days=review_period,
            stockout_cost_per_unit=stockout_cost,
            backorder_cost_per_unit_per_day=backorder_cost,
            storage_capacity=storage_capacity,
            allow_storage_over_capacity=node.allow_storage_over_capacity,
            storage_over_capacity_fixed_cost=storage_over_fixed,
            storage_over_capacity_variable_cost=storage_over_variable,
            service_level=service_level,
            moq=moq_map,
            order_multiple=order_multiple_map,
        )

    if node.node_type in {"material", "supplier"}:
        material_cost: Dict[str, float] = {}
        raw_costs = node.attributes.get("material_cost")
        if isinstance(raw_costs, dict):
            material_cost = {
                str(k): _to_float(v) for k, v in raw_costs.items() if v is not None
            }
        return MaterialNode(
            name=node.code,
            initial_stock=initial_stock,
            lead_time=node.lead_time_days or 0,
            storage_cost_fixed=storage_cost_fixed,
            storage_cost_variable=storage_cost_variable,
            backorder_enabled=backorder_enabled,
            lost_sales=lost_sales,
            review_period_days=review_period,
            stockout_cost_per_unit=stockout_cost,
            backorder_cost_per_unit_per_day=backorder_cost,
            storage_capacity=storage_capacity,
            allow_storage_over_capacity=node.allow_storage_over_capacity,
            storage_over_capacity_fixed_cost=storage_over_fixed,
            storage_over_capacity_variable_cost=storage_over_variable,
            material_cost=material_cost,
        )

    # factory (含む生産ノード)
    production_policies = list(node.production_policies or [])
    general_policy = next(
        (p for p in production_policies if p.item_code is None),
        None,
    )
    capacity = (
        general_policy.production_capacity if general_policy else None
    ) or sys.float_info.max
    allow_over_capacity = general_policy.allow_over_capacity if general_policy else True
    prod_fixed_cost = (
        _to_float(general_policy.production_cost_fixed) if general_policy else 0.0
    )
    prod_variable_cost = (
        _to_float(general_policy.production_cost_variable) if general_policy else 0.0
    )
    over_fixed = (
        _to_float(general_policy.over_capacity_fixed_cost) if general_policy else 0.0
    )
    over_variable = (
        _to_float(general_policy.over_capacity_variable_cost) if general_policy else 0.0
    )

    producible_products: List[str] = []
    for policy in production_policies:
        if policy.item_code:
            producible_products.append(policy.item_code)
    if not producible_products:
        producible_products = [
            item.code for item in items_by_code.values() if item.item_type == "product"
        ]
    producible_products = sorted({*producible_products})

    return FactoryNode(
        name=node.code,
        initial_stock=initial_stock,
        lead_time=node.lead_time_days or 0,
        storage_cost_fixed=storage_cost_fixed,
        storage_cost_variable=storage_cost_variable,
        backorder_enabled=backorder_enabled,
        lost_sales=lost_sales,
        review_period_days=review_period,
        stockout_cost_per_unit=stockout_cost,
        backorder_cost_per_unit_per_day=backorder_cost,
        storage_capacity=storage_capacity,
        allow_storage_over_capacity=node.allow_storage_over_capacity,
        storage_over_capacity_fixed_cost=storage_over_fixed,
        storage_over_capacity_variable_cost=storage_over_variable,
        service_level=service_level,
        producible_products=producible_products,
        production_capacity=capacity,
        production_cost_fixed=prod_fixed_cost,
        production_cost_variable=prod_variable_cost,
        allow_production_over_capacity=allow_over_capacity,
        production_over_capacity_fixed_cost=over_fixed,
        production_over_capacity_variable_cost=over_variable,
        reorder_point=reorder_point,
        order_up_to_level=order_up_to,
        moq=moq_map,
        order_multiple=order_multiple_map,
    )


def _build_network_link(arc: CanonicalArc) -> NetworkLink:
    min_order = {
        k: float(v) for k, v in (arc.min_order_qty or {}).items() if v is not None
    }
    order_multiple = {
        k: float(v) for k, v in (arc.order_multiple or {}).items() if v is not None
    }
    over_fixed = _to_float(arc.attributes.get("over_capacity_fixed_cost"))
    over_variable = _to_float(arc.attributes.get("over_capacity_variable_cost"))
    capacity = (
        arc.capacity_per_day if arc.capacity_per_day is not None else sys.float_info.max
    )
    return NetworkLink(
        from_node=arc.from_node,
        to_node=arc.to_node,
        transportation_cost_fixed=_to_float(arc.transportation_cost_fixed),
        transportation_cost_variable=_to_float(arc.transportation_cost_variable),
        lead_time=arc.lead_time_days or 0,
        capacity_per_day=capacity,
        allow_over_capacity=arc.allow_over_capacity,
        over_capacity_fixed_cost=over_fixed,
        over_capacity_variable_cost=over_variable,
        moq=min_order,
        order_multiple=order_multiple,
    )


def _build_customer_demand(row: DemandProfile) -> CustomerDemand:
    std_dev = row.std_dev if row.std_dev is not None else 0.0
    return CustomerDemand(
        store_name=row.node_code,
        product_name=row.item_code,
        demand_mean=row.mean,
        demand_std_dev=std_dev,
    )


def _convert_demand_family(
    rows: Optional[Iterable[Dict[str, Any]]],
) -> List[FamilyDemandRecord]:
    records: List[FamilyDemandRecord] = []
    for row in rows or []:
        family = row.get("family")
        period = row.get("period")
        if not family or not period:
            continue
        demand = _to_float(row.get("demand"), default=0.0)
        records.append(
            FamilyDemandRecord(family=str(family), period=str(period), demand=demand)
        )
    return records


def _convert_capacity(rows: Optional[Iterable[Dict[str, Any]]]) -> List[CapacityRecord]:
    records: List[CapacityRecord] = []
    for row in rows or []:
        workcenter = row.get("workcenter")
        period = row.get("period")
        if not workcenter or not period:
            continue
        capacity = _to_float(row.get("capacity"), default=0.0)
        records.append(
            CapacityRecord(
                workcenter=str(workcenter), period=str(period), capacity=capacity
            )
        )
    return records


def _convert_mix_share(
    rows: Optional[Iterable[Dict[str, Any]]],
) -> List[MixShareRecord]:
    records: List[MixShareRecord] = []
    for row in rows or []:
        family = row.get("family")
        sku = row.get("sku")
        if not family or not sku:
            continue
        share = _to_float(row.get("share"), default=0.0)
        records.append(MixShareRecord(family=str(family), sku=str(sku), share=share))
    return records


def _convert_item_master(
    rows: Optional[Iterable[Dict[str, Any]]],
) -> List[ItemMasterRecord]:
    records: List[ItemMasterRecord] = []
    for row in rows or []:
        item = row.get("item")
        if not item:
            continue
        lt = _to_int(row.get("lt"), default=0)
        lot = _to_float(row.get("lot"), default=1.0)
        moq = _to_float(row.get("moq"), default=0.0)
        records.append(ItemMasterRecord(item=str(item), lt=lt, lot=lot, moq=moq))
    return records


def _convert_inventory(
    rows: Optional[Iterable[Dict[str, Any]]],
) -> List[InventoryRecord]:
    records: List[InventoryRecord] = []
    for row in rows or []:
        item = row.get("item")
        loc = row.get("loc")
        if not item or not loc:
            continue
        qty = _to_float(row.get("qty"), default=0.0)
        records.append(InventoryRecord(item=str(item), loc=str(loc), qty=qty))
    return records


def _convert_open_po(rows: Optional[Iterable[Dict[str, Any]]]) -> List[OpenPORecord]:
    records: List[OpenPORecord] = []
    for row in rows or []:
        item = row.get("item")
        due = row.get("due")
        if not item or not due:
            continue
        qty = _to_float(row.get("qty"), default=0.0)
        records.append(OpenPORecord(item=str(item), due=str(due), qty=qty))
    return records


def _normalize_period_entries(
    rows: Optional[Iterable[Dict[str, Any]]], *, value_key: str
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in rows or []:
        period = row.get("period")
        if not period:
            continue
        value = _to_float(row.get(value_key), default=0.0)
        normalized.append({"period": str(period), value_key: value})
    return normalized


def _build_planning_bundle_from_canonical(
    config: CanonicalConfig,
) -> PlanningDataBundle:
    demand_family = [
        FamilyDemandRecord(
            family=profile.item_code,
            period=str(profile.bucket),
            demand=profile.mean,
        )
        for profile in config.demands
    ]

    capacity = [
        CapacityRecord(
            workcenter=cap.resource_code,
            period=str(cap.bucket),
            capacity=cap.capacity,
        )
        for cap in config.capacities
    ]

    item_master = [
        ItemMasterRecord(
            item=item.code,
            lt=int(item.lead_time_days or 0),
            lot=float(item.lot_size or 1.0),
            moq=float(item.min_order_qty or 0.0),
        )
        for item in config.items
    ]

    inventory_records: List[InventoryRecord] = []
    for node in config.nodes:
        for policy in node.inventory_policies:
            qty = policy.initial_inventory or 0.0
            if qty <= 0:
                continue
            inventory_records.append(
                InventoryRecord(item=policy.item_code, loc=node.code, qty=qty)
            )

    mix_share = []
    families = {record.family for record in demand_family}
    for family in families:
        mix_share.append(MixShareRecord(family=family, sku=family, share=1.0))

    open_po: List[OpenPORecord] = []

    period_cost: List[Dict[str, Any]] = []
    period_score: List[Dict[str, Any]] = []
    for calendar in config.calendars:
        definition = calendar.definition or {}
        period_cost.extend(
            _normalize_period_entries(definition.get("period_cost"), value_key="cost")
        )
        period_score.extend(
            _normalize_period_entries(definition.get("period_score"), value_key="score")
        )

    aggregate = AggregatePlanInput(
        demand_family=demand_family,
        capacity=capacity,
        mix_share=mix_share,
        item_master=item_master,
        inventory=inventory_records,
        open_po=open_po,
    )

    return PlanningDataBundle(
        aggregate_input=aggregate,
        period_cost=period_cost,
        period_score=period_score,
    )


def _to_float(value: Any, *, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, *, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "PlanningDataBundle",
    "build_simulation_input",
    "build_planning_inputs",
]
