from pathlib import Path

import pytest

from app import db
from app import plans_api as _plans_api
from app.plans_api import (
    get_plan_psi,
    get_plan_psi_events,
    get_plan_psi_state,
    post_plans_create_and_execute,
)
from core.config import load_canonical_config
from core.config.storage import save_canonical_config
from core.plan_repository import PlanRepository

pytestmark = pytest.mark.slow


def test_post_plans_integrated_run_with_canonical(db_setup, tmp_path):
    version_id = f"test-plan-{Path(tmp_path).name}"
    out_dir = tmp_path / "plan_out"
    config, _ = load_canonical_config(
        name="canonical-test",
        psi_input_path=Path("static/default_input.json"),
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

    res = post_plans_create_and_execute(body)

    try:
        assert res["version_id"] == version_id
        assert res["config_version_id"] == config_version_id
        storage_info = res.get("storage") or {}
        assert storage_info.get("plan_repository") == "stored"
        assert storage_info.get("series_rows", 0) > 0
        snapshot = db.get_plan_artifact(version_id, "canonical_snapshot.json")
        assert snapshot is not None
        planning_inputs = db.get_plan_artifact(version_id, "planning_inputs.json")
        assert planning_inputs is not None

        repo = PlanRepository(db._conn)
        series_rows = repo.fetch_plan_series(version_id, "aggregate")
        assert series_rows
        kpi_rows = repo.fetch_plan_kpis(version_id)
        assert kpi_rows

        psi_aggregate = get_plan_psi(version_id, level="aggregate", limit=10, offset=0)
        assert psi_aggregate["total"] > 0
        assert psi_aggregate["rows"]
        psi_detail = get_plan_psi(version_id, level="det", limit=10, offset=0)
        assert psi_detail["total"] > 0
        events_resp = get_plan_psi_events(
            version_id, level="aggregate", limit=5, offset=0
        )
        assert events_resp["total"] >= 0
        state_resp = get_plan_psi_state(version_id)
        assert "state" in state_resp
        if state_resp["state"]:
            assert "display_status" in state_resp["state"]

        plans_resp = _plans_api.get_plans(
            limit=10, offset=0, include="summary,kpi,jobs"
        )
        plan_entries = [
            p for p in plans_resp.get("plans", []) if p.get("version_id") == version_id
        ]
        assert plan_entries, "expected plan to appear in /plans response"
        plan_entry = plan_entries[0]
        summary = plan_entry.get("summary") or {}
        aggregate_series = (summary.get("series") or {}).get("aggregate", {})
        assert aggregate_series.get("rows", 0) > 0
        assert plan_entry.get("storage", {}).get("plan_repository") is True
        if summary.get("kpi"):
            assert "fill_rate" in summary["kpi"]
        legacy_resp = _plans_api.get_plans(limit=1, offset=0, include="legacy")
        assert isinstance(legacy_resp.get("plans"), list)
    finally:
        from app.db import _conn

        with _conn() as c:
            c.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
            c.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
            c.execute(
                "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
            )
            c.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
            c.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))
            c.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
            c.execute("DELETE FROM plan_versions WHERE version_id=?", (version_id,))
            c.execute(
                "DELETE FROM canonical_config_versions WHERE id=?",
                (config_version_id,),
            )


def test_post_plans_integrated_run_db_only_storage(db_setup, tmp_path):
    version_id = f"test-plan-storage-{Path(tmp_path).name}"
    out_dir = tmp_path / "plan_out"
    config, _ = load_canonical_config(
        name="canonical-test",
        psi_input_path=Path("static/default_input.json"),
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
        "storage_mode": "db",
    }

    res = post_plans_create_and_execute(body)

    try:
        assert res["version_id"] == version_id
        storage = res.get("storage") or {}
        assert storage.get("mode") == "db"
        assert storage.get("plan_repository") == "stored"
        assert res.get("artifacts") == []
        # PlanRepository has data, artifacts table remains empty
        repo = PlanRepository(db._conn)
        assert repo.fetch_plan_series(version_id, "aggregate")
        assert db.get_plan_artifact(version_id, "aggregate.json") is None
    finally:
        from app.db import _conn

        with _conn() as c:
            c.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
            c.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
            c.execute(
                "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
            )
            c.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
            c.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))
            c.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
            c.execute(
                "DELETE FROM canonical_config_versions WHERE id=?",
                (config_version_id,),
            )
