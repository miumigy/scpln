import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api import app
from app import db
import app.ui_runs as ui_runs_module
from app.ui_runs import ui_run_detail
from core.config.storage import create_planning_input_set

importlib.import_module("app.simulation_api")
importlib.import_module("app.ui_runs")

pytestmark = pytest.mark.slow


def test_ui_run_detail_page(db_setup):
    c = TestClient(app)
    p = {
        "planning_horizon": 1,
        "products": [{"name": "P1", "sales_price": 100}],
        "nodes": [{"node_type": "store", "name": "S1", "initial_stock": {"P1": 1}}],
        "network": [],
        "customer_demand": [
            {
                "store_name": "S1",
                "product_name": "P1",
                "demand_mean": 1,
                "demand_std_dev": 0,
            }
        ],
        "random_seed": 1,
    }
    rid = c.post("/simulation", json=p).json()["run_id"]
    r = c.get(f"/ui/runs/{rid}")
    assert r.status_code == 200
    assert "Run Detail" in r.text
    assert rid in r.text


def _insert_run(
    run_id: str,
    *,
    summary: dict,
    config_version_id: int | None = None,
    plan_version_id: str | None = None,
    input_set_label: str | None = None,
) -> None:
    now = int(time.time() * 1000)
    with db._conn() as conn:
        conn.execute(
            """
            INSERT INTO runs(
                run_id, started_at, duration_ms, schema_version, summary,
                results, daily_profit_loss, cost_trace, config_id, config_json,
                created_at, updated_at, scenario_id, config_version_id,
                plan_version_id, plan_job_id, input_set_label
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                now,
                0,
                "schema-1",
                json.dumps(summary, ensure_ascii=False),
                "[]",
                "[]",
                "[]",
                1,
                "{}",
                now,
                now,
                None,
                config_version_id,
                plan_version_id,
                None,
                input_set_label,
            ),
        )


class _DummyRegistry:
    def get(self, run_id: str):
        return None


def test_ui_run_detail_shows_recorded_input_set(db_setup, monkeypatch):
    monkeypatch.setattr(ui_runs_module, "_get_registry", lambda: _DummyRegistry())
    label = f"run-input-{int(time.time())}"
    plan_version_id = f"run-plan-{int(time.time())}"
    create_planning_input_set(
        config_version_id=100,
        label=label,
        status="ready",
        source="ui",
    )
    db.create_plan_version(
        plan_version_id,
        status="active",
        config_version_id=100,
        input_set_label=label,
    )
    run_id = f"run-{int(time.time())}"
    summary = {"_plan_version_id": plan_version_id, "_input_set_label": label}
    _insert_run(
        run_id,
        summary=summary,
        config_version_id=100,
        plan_version_id=plan_version_id,
        input_set_label=label,
    )
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = ui_run_detail(request, run_id)
    isi = response.context["input_set_info"]
    assert isi["label"] == label
    assert isi["legacy"] is False
    assert isi["missing"] is False
    assert isi["inferred"] is False


def test_ui_run_detail_infers_input_set_when_missing_label(db_setup, monkeypatch):
    monkeypatch.setattr(ui_runs_module, "_get_registry", lambda: _DummyRegistry())
    label = f"run-input-miss-{int(time.time())}"
    create_planning_input_set(
        config_version_id=100,
        label=label,
        status="ready",
        source="ui",
    )
    run_id = f"run-miss-{int(time.time())}"
    _insert_run(run_id, summary={}, config_version_id=100)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = ui_run_detail(request, run_id)
    isi = response.context["input_set_info"]
    assert isi["label"] == label
    assert isi["legacy"] is False
    assert isi["missing"] is False
    assert isi["inferred"] is True
