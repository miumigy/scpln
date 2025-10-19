import importlib

import pytest
from fastapi.testclient import TestClient

from app.api import app

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
