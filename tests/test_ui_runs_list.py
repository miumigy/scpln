import importlib

import pytest
from fastapi.testclient import TestClient

from app.api import app

# 必要APIを有効化
importlib.import_module("app.simulation_api")
importlib.import_module("app.run_list_api")  # 既存
importlib.import_module("app.trace_export_api")  # 既存なら
importlib.import_module("app.ui_runs")

pytestmark = pytest.mark.slow


def test_ui_runs_list_basic(db_setup):
    c = TestClient(app)
    # ランを少なくとも1つ作る
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
    c.post("/simulation", json=payload)
    r = c.get("/ui/runs")
    assert r.status_code == 200
    assert "<table" in r.text or "まだランはありません" in r.text
