import json
import time

import pytest
from fastapi.testclient import TestClient

from app import db
from app.metrics import (
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
)
from core.plan_repository import PlanRepository
from app.run_registry_db import RunRegistryDB

pytestmark = pytest.mark.slow


def test_plans_integrated_run_and_reconcile_e2e(seed_canonical_data, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")

    from main import app

    client = TestClient(app)
    ver = f"testv-{int(time.time())}"
    # integrated run
    r = client.post(
        "/plans/create_and_execute",
        json={
            "version_id": ver,
            "config_version_id": 100,
            "weeks": 4,
            "round_mode": "int",
            "lt_unit": "day",
            "cutover_date": "2025-01-15",
            "anchor_policy": "blend",
            "apply_adjusted": False,
            "lightweight": True,
        },
        timeout=120,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("version_id") == ver
    repo = PlanRepository(
        db._conn,
        PLAN_DB_WRITE_LATENCY,
        PLAN_SERIES_ROWS_TOTAL,
        PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    )
    assert repo.fetch_plan_series(
        ver, "aggregate"
    ), "PlanRepositoryにaggregate行が書き込まれていること"
    assert repo.fetch_plan_kpis(ver), "PlanRepositoryにKPIが書き込まれていること"
    # list
    r = client.get("/plans")
    assert r.status_code == 200
    assert any(p.get("version_id") == ver for p in r.json().get("plans", []))
    # summary
    r = client.get(f"/plans/{ver}/summary")
    assert r.status_code == 200
    # reconcile (before only)
    r = client.post(f"/plans/{ver}/reconcile", json={"tol_abs": 1e-6, "tol_rel": 1e-6})
    assert r.status_code == 200
    assert r.json().get("version_id") == ver


def test_delete_plan_api(db_setup, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    from main import app

    client = TestClient(app)
    version_id = "plan-del-test"
    db.create_plan_version(version_id, status="active")

    repo = PlanRepository(
        db._conn,
        PLAN_DB_WRITE_LATENCY,
        PLAN_SERIES_ROWS_TOTAL,
        PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    )
    repo.write_plan(
        version_id,
        series=[
            {
                "version_id": version_id,
                "level": "aggregate",
                "time_bucket_type": "week",
                "time_bucket_key": "2025-W01",
                "item_key": "FG1",
                "location_key": "SITE",
                "demand": 10.0,
                "supply": 12.0,
            }
        ],
        kpis=[
            {
                "version_id": version_id,
                "metric": "fill_rate",
                "bucket_type": "total",
                "bucket_key": "all",
                "value": 0.95,
            }
        ],
    )
    db.upsert_plan_artifact(
        version_id,
        "plan_final.json",
        json.dumps({"dummy": True}, ensure_ascii=False),
    )

    registry = RunRegistryDB()
    run_id = "run-uses-plan"
    registry.put(
        run_id,
        {
            "run_id": run_id,
            "plan_version_id": version_id,
            "summary": {"_plan_version_id": version_id},
        },
    )

    resp = client.delete(f"/plans/{version_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "deleted", "version_id": version_id}

    assert db.get_plan_version(version_id) is None
    assert db.get_plan_artifact(version_id, "plan_final.json") is None
    assert repo.fetch_plan_series(version_id, "aggregate") == []
    run_row = registry.get(run_id)
    assert run_row.get("plan_version_id") is None
    assert "_plan_version_id" not in run_row.get("summary", {})
