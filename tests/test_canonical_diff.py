from core.config import (
    CanonicalArc,
    CanonicalConfig,
    CanonicalItem,
    CanonicalNode,
    ConfigMeta,
    diff_canonical_configs,
)


def _build_config(name: str) -> CanonicalConfig:
    return CanonicalConfig(
        meta=ConfigMeta(name=name, status="draft"),
        items=[CanonicalItem(code="SKU-A"), CanonicalItem(code="SKU-B")],
        nodes=[
            CanonicalNode(code="N1", node_type="store", name="Store-1"),
        ],
        arcs=[
            CanonicalArc(from_node="N1", to_node="N1", arc_type="transport"),
        ],
        bom=[],
        demands=[],
        capacities=[],
        calendars=[],
        hierarchies=[],
    )


def test_diff_canonical_configs_detects_changes():
    base = _build_config("baseline")
    compare = _build_config("compare")
    # 変更: status, name, items, arcs
    compare.meta.status = "active"
    compare.items.append(CanonicalItem(code="SKU-C"))
    compare.nodes[0].name = "Store-1R"
    compare.arcs[0].capacity_per_day = 10

    diff = diff_canonical_configs(base, compare)

    meta_changes = diff["meta"]["field_changes"]
    assert meta_changes["status"]["base"] == "draft"
    assert meta_changes["status"]["compare"] == "active"

    items_diff = diff["entities"]["items"]
    assert "SKU-C" in items_diff.added

    nodes_diff = diff["entities"]["nodes"]
    assert "N1" in nodes_diff.changed

    arcs_diff = diff["entities"]["arcs"]
    assert arcs_diff.base_count == 1
    assert arcs_diff.compare_count == 1
