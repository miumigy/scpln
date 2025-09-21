from pathlib import Path

from core.config import load_canonical_config


def test_load_canonical_config_smoke() -> None:
    base = Path(__file__).resolve().parents[1]
    psi_path = base / "static" / "default_input.json"
    planning_dir = base / "samples" / "planning"
    product_hierarchy = base / "configs" / "product_hierarchy.json"
    location_hierarchy = base / "configs" / "location_hierarchy.json"

    config, validation = load_canonical_config(
        name="smoke",
        psi_input_path=psi_path,
        planning_dir=planning_dir,
        product_hierarchy_path=product_hierarchy,
        location_hierarchy_path=location_hierarchy,
    )

    assert config.meta.name == "smoke"
    assert any(item.code == "完成品A" for item in config.items)
    assert any(node.code == "店舗1" for node in config.nodes)
    assert any(bom.parent_item == "完成品A" for bom in config.bom)
    assert validation is not None
    assert not validation.has_errors

