from pathlib import Path

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


def test_build_planning_inputs_from_payload():
    config = _load_config()

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


def test_build_planning_inputs_without_payload_fallback():
    config = _load_config().model_copy(deep=True)
    attrs = dict(config.meta.attributes or {})
    attrs.pop("planning_payload", None)
    sources = dict(attrs.get("sources") or {})
    sources.pop("planning_dir", None)
    attrs["sources"] = sources
    config.meta.attributes = attrs

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


def test_build_planning_inputs_uses_planning_dir_when_payload_missing():
    config = _load_config().model_copy(deep=True)
    attrs = dict(config.meta.attributes or {})
    attrs.pop("planning_payload", None)
    config.meta.attributes = attrs

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


def test_build_planning_inputs_trims_calendar_to_canonical_demand():
    config = _load_config().model_copy(deep=True)

    attrs = dict(config.meta.attributes or {})
    payload = dict(attrs.get("planning_payload") or {})
    demand_rows = [dict(row) for row in payload.get("demand_family", [])]
    if not demand_rows:
        pytest.skip("planning payload does not contain demand rows")

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
