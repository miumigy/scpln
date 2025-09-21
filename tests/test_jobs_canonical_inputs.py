from pathlib import Path

from core.config import build_planning_inputs, load_canonical_config
from app import jobs


def test_materialize_planning_inputs_creates_required_files(tmp_path):
    base = Path(__file__).resolve().parents[1]
    config, _ = load_canonical_config(
        name="test",
        psi_input_path=base / "static" / "default_input.json",
        planning_dir=base / "samples" / "planning",
        product_hierarchy_path=base / "configs" / "product_hierarchy.json",
        location_hierarchy_path=base / "configs" / "location_hierarchy.json",
    )
    bundle = build_planning_inputs(config)

    jobs._materialize_planning_inputs(bundle, tmp_path)

    expected = [
        "aggregate_input.json",
        "demand_family.csv",
        "capacity.csv",
        "mix_share.csv",
        "item.csv",
        "inventory.csv",
    ]

    for name in expected:
        assert (tmp_path / name).exists()

    demand_csv = (tmp_path / "demand_family.csv").read_text(encoding="utf-8")
    assert "family,period,demand" in demand_csv.splitlines()[0]
