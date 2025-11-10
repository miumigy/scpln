from pathlib import Path
from typing import Dict, Optional

import pytest

from core.config import (
    CanonicalConfig,
    CanonicalItem,
    CanonicalNode,
    ConfigMeta,
    DemandProfile,
    build_planning_inputs,
    build_simulation_input,
    load_canonical_config,
)
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
from core.config.storage import PlanningInputSetNotFoundError


def _payload_to_input_set(config: CanonicalConfig) -> Optional[PlanningInputSet]:
    attrs = dict(config.meta.attributes or {})
    payload = dict(attrs.get("planning_payload") or {})
    if not payload:
        return None

    config.meta.version_id = config.meta.version_id or 1
    aggregates = PlanningInputAggregates(
        family_demands=[
            PlanningFamilyDemand(
                family_code=str(row.get("family")),
                period=str(row.get("period")),
                demand=float(row.get("demand") or 0.0),
            )
            for row in payload.get("demand_family", [])
            if row.get("family") and row.get("period")
        ],
        capacity_buckets=[
            PlanningCapacityBucket(
                resource_code=str(row.get("workcenter") or row.get("resource_code")),
                resource_type=row.get("resource_type") or "workcenter",
                period=str(row.get("period")),
                capacity=float(row.get("capacity") or 0.0),
            )
            for row in payload.get("capacity", [])
            if (row.get("workcenter") or row.get("resource_code")) and row.get("period")
        ],
        mix_shares=[
            PlanningMixShare(
                family_code=str(row.get("family") or row.get("family_code")),
                sku_code=str(row.get("sku") or row.get("sku_code")),
                share=float(row.get("share") or 0.0),
            )
            for row in payload.get("mix_share", [])
            if (row.get("family") or row.get("family_code"))
            and (row.get("sku") or row.get("sku_code"))
        ],
        inventory_snapshots=[
            PlanningInventorySnapshot(
                node_code=str(row.get("loc") or row.get("node_code")),
                item_code=str(row.get("item") or row.get("item_code")),
                initial_qty=float(row.get("qty") or row.get("initial_qty") or 0.0),
            )
            for row in payload.get("inventory", [])
            if (row.get("loc") or row.get("node_code"))
            and (row.get("item") or row.get("item_code"))
        ],
        inbound_orders=[
            PlanningInboundOrder(
                po_id=row.get("po_id"),
                item_code=str(row.get("item") or row.get("item_code")),
                due_date=str(row.get("due") or row.get("due_date")),
                qty=float(row.get("qty") or 0.0),
            )
            for row in payload.get("open_po", [])
            if (row.get("item") or row.get("item_code"))
            and (row.get("due") or row.get("due_date"))
        ],
        period_metrics=[
            PlanningPeriodMetric(
                metric_code="cost",
                period=str(row.get("period")),
                value=float(row.get("cost") or 0.0),
            )
            for row in payload.get("period_cost", [])
            if row.get("period")
        ]
        + [
            PlanningPeriodMetric(
                metric_code="score",
                period=str(row.get("period")),
                value=float(row.get("score") or 0.0),
            )
            for row in payload.get("period_score", [])
            if row.get("period")
        ],
    )

    calendar_spec = None
    if payload.get("planning_calendar"):
        calendar_spec = PlanningCalendarSpec(**payload["planning_calendar"])

    return PlanningInputSet(
        id=1,
        config_version_id=config.meta.version_id,
        label="test-input-set",
        status="ready",
        source="csv",
        aggregates=aggregates,
        calendar_spec=calendar_spec,
    )


def _mock_planning_input_set(monkeypatch, config: CanonicalConfig):
    input_set = _payload_to_input_set(config)
    assert input_set is not None

    def _fake_get_planning_input_set(**kwargs):
        return input_set

    monkeypatch.setattr(
        "core.config.builders.get_planning_input_set",
        _fake_get_planning_input_set,
    )
    return input_set


def _mock_no_input_set(monkeypatch):
    def _raise(**kwargs):
        raise PlanningInputSetNotFoundError("not found")

    monkeypatch.setattr(
        "core.config.builders.get_planning_input_set",
        _raise,
    )


def _load_config():
    base = Path(__file__).resolve().parents[1]
    config, validation = load_canonical_config(
        name="test",
        psi_input_path=base / "static" / "default_input.json",
        planning_dir=base / "samples" / "planning",
        product_hierarchy_path=base / "configs" / "product_hierarchy.json",
        location_hierarchy_path=base / "configs" / "location_hierarchy.json",
    )
    assert validation is not None and not validation.has_errors
    return config


def test_build_simulation_input_from_canonical():
    config = _load_config()

    sim_input = build_simulation_input(config, planning_horizon=120, random_seed=42)

    assert sim_input.planning_horizon == 120
    assert sim_input.random_seed == 42

    product_names = {product.name for product in sim_input.products}
    assert {"完成品A", "完成品B"}.issubset(product_names)

    store = next(
        node
        for node in sim_input.nodes
        if getattr(node, "node_type", "") == "store" and node.name == "店舗1"
    )
    assert store.initial_stock["完成品A"] == 30
    assert store.moq["完成品A"] == 10

    factory = next(
        node for node in sim_input.nodes if getattr(node, "node_type", "") == "factory"
    )
    assert "完成品A" in factory.producible_products
    assert factory.production_capacity > 0

    link = next(
        lk
        for lk in sim_input.network
        if lk.from_node == "中央倉庫" and lk.to_node == "店舗1"
    )
    assert link.lead_time == 3

    demand = next(d for d in sim_input.customer_demand if d.product_name == "完成品A")
    assert demand.demand_mean == 15


def test_build_simulation_input_distributes_period_demands():
    config = CanonicalConfig(
        meta=ConfigMeta(name="period", attributes={"planning_horizon": 90}),
        items=[
            CanonicalItem(
                code="SKU-A",
                name="SKU-A",
                item_type="product",
                unit_cost=1500.0,
                attributes={"sales_price": 2400},
            )
        ],
        nodes=[
            CanonicalNode(
                code="STORE1",
                name="Store 1",
                node_type="store",
                inventory_policies=[],
            )
        ],
        arcs=[],
        bom=[],
        demands=[
            DemandProfile(
                node_code="STORE1", item_code="SKU-A", bucket="M1", mean=90.0
            ),
            DemandProfile(
                node_code="STORE1", item_code="SKU-A", bucket="M2", mean=60.0
            ),
            DemandProfile(
                node_code="STORE1", item_code="SKU-A", bucket="M3", mean=30.0
            ),
        ],
        capacities=[],
        calendars=[],
        hierarchies=[],
    )

    sim_input = build_simulation_input(config)

    product = next(p for p in sim_input.products if p.name == "SKU-A")
    assert product.unit_cost == pytest.approx(1500.0)

    demands = [d for d in sim_input.customer_demand if d.product_name == "SKU-A"]
    assert [(d.start_day, d.end_day) for d in demands] == [(1, 30), (31, 60), (61, 90)]

    totals = [
        pytest.approx(d.demand_mean * (d.end_day - d.start_day + 1)) for d in demands
    ]
    assert totals == [pytest.approx(90.0), pytest.approx(60.0), pytest.approx(30.0)]


def test_build_planning_inputs_from_payload(monkeypatch):
    config = _load_config()
    _mock_planning_input_set(monkeypatch, config)

    bundle = build_planning_inputs(config)
    aggregate = bundle.aggregate_input

    canonical_total = sum(float(d.mean or 0.0) for d in config.demands)
    payload_total = sum(
        float(record.demand or 0.0) for record in aggregate.demand_family
    )
    assert payload_total == pytest.approx(canonical_total, rel=1e-6)

    families = sorted({record.family for record in aggregate.demand_family})
    expected_families = sorted({profile.item_code for profile in config.demands})
    assert families == expected_families

    periods = sorted({record.period for record in aggregate.demand_family})
    expected_periods = sorted({str(profile.bucket) for profile in config.demands})
    assert periods == expected_periods

    for family in families:
        shares = [
            float(record.share or 0.0)
            for record in aggregate.mix_share
            if record.family == family
        ]
        assert shares and sum(shares) == pytest.approx(1.0)

    assert bundle.planning_calendar is not None


def test_build_planning_inputs_prefers_label(monkeypatch):
    config = _load_config()
    input_set = _payload_to_input_set(config)
    if input_set is None:
        pytest.skip("planning payload missing in seed config")
    attrs = dict(config.meta.attributes or {})
    attrs["planning_input_label"] = "custom_label"
    config.meta.attributes = attrs

    captured: Dict[str, Any] = {}

    def _fake_get_planning_input_set(**kwargs):
        captured["label"] = kwargs.get("label")
        return input_set

    monkeypatch.setattr(
        "core.config.builders.get_planning_input_set", _fake_get_planning_input_set
    )

    bundle = build_planning_inputs(config)
    assert bundle.aggregate_input.demand_family
    assert captured.get("label") == "custom_label"


def test_build_planning_inputs_without_payload_fallback(monkeypatch):
    config = _load_config().model_copy(deep=True)
    attrs = dict(config.meta.attributes or {})
    attrs.pop("planning_payload", None)
    sources = dict(attrs.get("sources") or {})
    sources.pop("planning_dir", None)
    attrs["sources"] = sources
    config.meta.attributes = attrs
    config.meta.version_id = 1
    _mock_no_input_set(monkeypatch)

    bundle = build_planning_inputs(config)
    aggregate = bundle.aggregate_input

    canonical_total = sum(float(d.mean or 0.0) for d in config.demands)
    payload_total = sum(
        float(record.demand or 0.0) for record in aggregate.demand_family
    )
    assert payload_total == pytest.approx(canonical_total, rel=1e-6)

    families = sorted({record.family for record in aggregate.demand_family})
    expected_families = sorted({profile.item_code for profile in config.demands})
    assert families == expected_families

    periods = sorted({record.period for record in aggregate.demand_family})
    expected_periods = sorted({str(profile.bucket) for profile in config.demands})
    assert periods == expected_periods

    for family in families:
        shares = [
            float(record.share or 0.0)
            for record in aggregate.mix_share
            if record.family == family
        ]
        assert shares and sum(shares) == pytest.approx(1.0)


def test_build_planning_inputs_uses_planning_dir_when_payload_missing(monkeypatch):
    config = _load_config().model_copy(deep=True)
    attrs = dict(config.meta.attributes or {})
    attrs.pop("planning_payload", None)
    config.meta.attributes = attrs
    config.meta.version_id = 1
    _mock_no_input_set(monkeypatch)

    bundle = build_planning_inputs(config)

    aggregate = bundle.aggregate_input
    canonical_total = sum(float(d.mean or 0.0) for d in config.demands)
    payload_total = sum(
        float(record.demand or 0.0) for record in aggregate.demand_family
    )
    assert payload_total == pytest.approx(canonical_total, rel=1e-6)

    families = sorted({record.family for record in aggregate.demand_family})
    expected_families = sorted({profile.item_code for profile in config.demands})
    assert families == expected_families

    periods = sorted({record.period for record in aggregate.demand_family})
    expected_periods = sorted({str(profile.bucket) for profile in config.demands})
    assert periods == expected_periods


def test_build_planning_inputs_trims_calendar_to_canonical_demand(monkeypatch):
    config = _load_config().model_copy(deep=True)

    attrs = dict(config.meta.attributes or {})
    payload = dict(attrs.get("planning_payload") or {})
    demand_rows = [dict(row) for row in payload.get("demand_family", [])]
    if not demand_rows:
        pytest.skip("planning payload does not contain demand rows")
    _mock_planning_input_set(monkeypatch, config)

    bundle = build_planning_inputs(config)
    assert bundle.planning_calendar is not None

    periods = bundle.planning_calendar["periods"]
    assert periods

    sim_input = build_simulation_input(config)
    horizon = sim_input.planning_horizon

    weeks = [
        week
        for period in periods
        for week in period.get("weeks", [])
        if "weight" in week
    ]
    total_days = sum(float(week["weight"]) for week in weeks)
    assert total_days >= horizon
    if weeks:
        total_days_without_last = total_days - float(weeks[-1]["weight"])
        assert total_days_without_last < horizon

    week_sequences = [week["sequence"] for week in weeks]
    assert week_sequences == list(range(1, len(week_sequences) + 1))


def test_build_planning_inputs_scales_initial_inventory():
    config = CanonicalConfig(
        meta=ConfigMeta(
            name="scale-test",
            attributes={"initial_inventory_scale": 2.0},
        ),
        items=[
            CanonicalItem(
                code="SKU-X",
                name="SKU-X",
                item_type="product",
                unit_cost=100,
            )
        ],
        nodes=[
            CanonicalNode(
                code="WH",
                name="Warehouse",
                node_type="warehouse",
                inventory_policies=[{"item_code": "SKU-X", "initial_inventory": 15}],
            )
        ],
        arcs=[],
        bom=[],
        demands=[
            DemandProfile(
                node_code="WH",
                item_code="SKU-X",
                bucket="M1",
                mean=10.0,
            )
        ],
        capacities=[],
        calendars=[],
        hierarchies=[],
    )

    bundle = build_planning_inputs(config)
    inventory = bundle.aggregate_input.inventory
    assert inventory
    assert inventory[0].item == "SKU-X"
    assert inventory[0].qty == pytest.approx(30.0)
