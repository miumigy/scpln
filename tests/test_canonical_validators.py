from core.config import (
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
    validate_canonical_config,
)


def _base_config() -> CanonicalConfig:
    meta = ConfigMeta(name="unit-test")
    items = [
        CanonicalItem(code="FG_A", name="製品A"),
        CanonicalItem(code="RM_X", name="原材料X", item_type="material"),
    ]
    nodes = [
        CanonicalNode(
            code="STORE1",
            node_type="store",
            inventory_policies=[
                NodeInventoryPolicy(item_code="FG_A", initial_inventory=10.0),
            ],
        ),
        CanonicalNode(
            code="FACT1",
            node_type="factory",
            inventory_policies=[
                NodeInventoryPolicy(item_code="RM_X", initial_inventory=100.0),
            ],
        ),
    ]
    arcs = [
        CanonicalArc(from_node="FACT1", to_node="STORE1"),
    ]
    bom = [
        CanonicalBom(parent_item="FG_A", child_item="RM_X", quantity=2.0),
    ]
    demands = [
        DemandProfile(node_code="STORE1", item_code="FG_A", bucket="W1", mean=10.0),
    ]
    capacities = [
        CapacityProfile(resource_code="FACT1", bucket="W1", capacity=100.0),
    ]
    calendars = [
        CalendarDefinition(calendar_code="DEFAULT"),
    ]
    hierarchies = [
        HierarchyEntry(hierarchy_type="product", node_key="FG_A"),
    ]

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


def test_validate_config_ok() -> None:
    result = validate_canonical_config(_base_config())
    assert not result.has_errors
    assert result.issues == []


def test_duplicate_node_detected() -> None:
    config = _base_config()
    config.nodes.append(config.nodes[0].model_copy())
    result = validate_canonical_config(config)
    assert result.has_errors
    assert any(issue.code == "DUPLICATE_NODE" for issue in result.issues)


def test_arc_missing_node_detected() -> None:
    config = _base_config()
    config.arcs.append(CanonicalArc(from_node="UNKNOWN", to_node="STORE1"))
    result = validate_canonical_config(config)
    assert result.has_errors
    assert any(issue.code == "ARC_FROM_MISSING" for issue in result.issues)


def test_bom_cycle_detected() -> None:
    config = _base_config()
    config.bom.append(CanonicalBom(parent_item="RM_X", child_item="FG_A", quantity=1.0))
    result = validate_canonical_config(config)
    assert result.has_errors
    assert any(issue.code == "BOM_CYCLE" for issue in result.issues)
