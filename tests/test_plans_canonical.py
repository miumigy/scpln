from pathlib import Path

from app import db
from app.plans_api import post_plans_integrated_run
from core.config import load_canonical_config
from core.config.storage import save_canonical_config

def test_post_plans_integrated_run_with_canonical(db_setup, tmp_path):
    version_id = f"test-plan-{Path(tmp_path).name}"
    out_dir = tmp_path / "plan_out"
    config, _ = load_canonical_config(
        name="canonical-test",
        psi_input_path=Path("static/default_input.json"),
        planning_dir=Path("samples/planning"),
        product_hierarchy_path=Path("configs/product_hierarchy.json"),
        location_hierarchy_path=Path("configs/location_hierarchy.json"),
        include_validation=False,
    )
    config_version_id = save_canonical_config(config)
    body = {
        "version_id": version_id,
        "config_version_id": config_version_id,
        "out_dir": str(out_dir),
        "weeks": 2,
        "round_mode": "int",
        "lt_unit": "day",
    }

    res = post_plans_integrated_run(body)

    try:
        assert res["version_id"] == version_id
        assert res["config_version_id"] == config_version_id
        snapshot = db.get_plan_artifact(version_id, "canonical_snapshot.json")
        assert snapshot is not None
        planning_inputs = db.get_plan_artifact(version_id, "planning_inputs.json")
        assert planning_inputs is not None
    finally:
        from app.db import _conn

        with _conn() as c:
            c.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
            c.execute("DELETE FROM plan_versions WHERE version_id=?", (version_id,))
            c.execute(
                "DELETE FROM canonical_config_versions WHERE id=?",
                (config_version_id,),
            )