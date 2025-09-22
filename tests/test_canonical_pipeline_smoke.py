import json
from pathlib import Path

import pytest

from core.config import (
    build_planning_inputs,
    build_simulation_input,
    load_canonical_config,
)


@pytest.fixture(scope="module")
def canonical_config():
    base = Path(__file__).resolve().parents[1]
    config, validation = load_canonical_config(
        name="pipeline-smoke",
        psi_input_path=base / "static" / "default_input.json",
        planning_dir=base / "samples" / "planning",
        product_hierarchy_path=base / "configs" / "product_hierarchy.json",
        location_hierarchy_path=base / "configs" / "location_hierarchy.json",
    )
    assert validation is not None and not validation.has_errors
    return config


def test_builders_smoke(canonical_config, tmp_path):
    sim_input = build_simulation_input(canonical_config)
    planning_bundle = build_planning_inputs(canonical_config)

    # PSI出力をJSON化しサンプル構造を確認
    sim_json = json.loads(sim_input.model_dump_json())
    assert sim_json["planning_horizon"] > 0
    assert any(prod["name"] == "完成品A" for prod in sim_json["products"])

    # Planning向けデータをAggregatePlanInputスキーマで検証
    agg = planning_bundle.aggregate_input
    assert agg.demand_family
    assert agg.capacity
    assert agg.mix_share

    # JSON出力してplanningパイプラインに渡せる形式であることを確認
    planning_json_path = tmp_path / "aggregate_input.json"
    planning_json_path.write_text(agg.model_dump_json(indent=2), encoding="utf-8")
    assert planning_json_path.exists()
