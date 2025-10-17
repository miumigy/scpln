from pathlib import Path

from core.config import (
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


def test_build_planning_inputs_from_payload():
    config = _load_config()

    bundle = build_planning_inputs(config)
    aggregate = bundle.aggregate_input

    assert aggregate.schema_version == "agg-1.0"
    assert any(
        record.family == "F1" and record.period == "2025-01"
        for record in aggregate.demand_family
    )

    mix_entry = next(
        record
        for record in aggregate.mix_share
        if record.family == "F1" and record.sku == "SKU1"
    )
    assert mix_entry.share == 0.6

    assert any(entry["period"] == "2025-01" for entry in bundle.period_cost)


def test_build_planning_inputs_without_payload_fallback():
    config = _load_config().model_copy(deep=True)
    config.meta.attributes.pop("planning_payload", None)

    bundle = build_planning_inputs(config)
    aggregate = bundle.aggregate_input

    assert len(aggregate.demand_family) == 2
    assert all(
        record.family in {d.item_code for d in config.demands}
        for record in aggregate.demand_family
    )
    assert all(record.share == 1.0 for record in aggregate.mix_share)
