
import importlib
from fastapi.testclient import TestClient
from app.api import app
from app.run_registry import REGISTRY

importlib.import_module("app.simulation_api")
importlib.import_module("app.ui_runs")
importlib.import_module("app.ui_compare")


def test_ui_compare_preset_roundtrip():
    c = TestClient(app)
    REGISTRY.clear()
    p = {
        "planning_horizon": 2,
        "products": [{"name": "P1", "sales_price": 100}],
        "nodes": [{"node_type": "store", "name": "S1", "initial_stock": {"P1": 5}}],
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
    # シナリオ付きで実行結果を登録
    id1 = c.post("/simulation?scenario_id=1", json=p).json()["run_id"]
    p["customer_demand"][0]["demand_mean"] = 2
    id2 = c.post("/simulation?scenario_id=2", json=p).json()["run_id"]
    p["customer_demand"][0]["demand_mean"] = 3
    id3 = c.post("/simulation?scenario_id=3", json=p).json()["run_id"]

    # プリセットエンドポイントをテスト
    r = c.get("/ui/compare/preset?base_scenario=1&target_scenarios=2,3")
    assert r.status_code == 200
    assert "Compare" in r.text
    # 最新の実行IDが使われることを確認
    assert id1 in r.text
    assert id2 in r.text
    assert id3 in r.text

def test_ui_compare_preset_bad_requests():
    c = TestClient(app)
    REGISTRY.clear()
    # target_scenarios がない
    r = c.get("/ui/compare/preset?base_scenario=1")
    assert r.status_code == 400
    # 実行結果が見つからない
    r = c.get("/ui/compare/preset?base_scenario=998&target_scenarios=999")
    assert r.status_code == 404
