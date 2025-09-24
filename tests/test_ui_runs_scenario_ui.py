import importlib
from fastapi.testclient import TestClient

# 有効なルートを登録
importlib.import_module("app.simulation_api")
importlib.import_module("app.run_list_api")
importlib.import_module("app.ui_runs")

from app.api import app


def test_ui_runs_shows_scenario_column_and_value(db_setup):
    c = TestClient(app)
    payload = {
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
    sid = 777
    r = c.post(f"/simulation?scenario_id={sid}", json=payload)
    assert r.status_code == 200

    page = c.get("/ui/runs")
    assert page.status_code == 200
    html = page.text
    assert "scenario_id" in html
    assert str(sid) in html


def test_ui_run_detail_shows_scenario_id(db_setup):
    c = TestClient(app)
    payload = {
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
    sid = 888
    r = c.post(f"/simulation?scenario_id={sid}", json=payload)
    assert r.status_code == 200
    rid = r.json()["run_id"]
    detail = c.get(f"/ui/runs/{rid}")
    assert detail.status_code == 200
    assert "scenario_id" in detail.text
    assert str(sid) in detail.text
