import importlib
from fastapi.testclient import TestClient
from app.api import app

importlib.import_module("app.simulation_api")
importlib.import_module("app.ui_runs")
importlib.import_module("app.ui_compare")


def test_ui_compare_page_roundtrip():
    c = TestClient(app)
    p = {
        "planning_horizon": 2,
        "products": [{"name": "P1", "sales_price": 100}],
        "nodes": [{"node_type": "store", "name": "S1", "initial_stock": {"P1": 5}}],
        "network": [],
        "customer_demand": [
            {"store_name": "S1", "product_name": "P1", "demand_mean": 1, "demand_std_dev": 0}
        ],
        "random_seed": 1,
    }
    id1 = c.post("/simulation", json=p).json()["run_id"]
    p["customer_demand"][0]["demand_mean"] = 3
    id2 = c.post("/simulation", json=p).json()["run_id"]
    # /ui/compare は POST（フォーム）
    r = c.post("/ui/compare", data={"run_ids": f"{id1},{id2}"})
    assert r.status_code == 200
    assert "Compare" in r.text
    assert id1 in r.text and id2 in r.text

