import importlib
import time
from fastapi.testclient import TestClient
from app.api import app
from app import db

# 有効化
importlib.import_module("app.ui_scenarios")
importlib.import_module("app.jobs_api")
importlib.import_module("app.simulation_api")


def test_ui_scenarios_run_with_config():
    c = TestClient(app)
    # 準備: シナリオと設定を作成
    sid = db.create_scenario(name="ScA", parent_id=None, tag=None, description=None)
    cfg_json = {
        "planning_horizon": 1,
        "products": [{"name": "P1", "sales_price": 100}],
        "nodes": [{"node_type": "store", "name": "S1", "initial_stock": {"P1": 1}}],
        "network": [],
        "customer_demand": [
            {"store_name": "S1", "product_name": "P1", "demand_mean": 1, "demand_std_dev": 0}
        ],
        "random_seed": 1,
    }
    cfg_id = db.create_config(name="CfgA", json_text=db.json_dumps(cfg_json) if hasattr(db, 'json_dumps') else __import__('json').dumps(cfg_json, ensure_ascii=False))

    # 実行: UI経由でRun（ジョブ投入）
    r = c.post(f"/ui/scenarios/{sid}/run", data={"config_id": cfg_id})
    assert r.status_code == 303
    # ジョブが作成され、完了までポーリング
    # ジョブ一覧APIを利用
    done = False
    for _ in range(50):
        rows = c.get("/jobs?limit=5").json().get("jobs", [])
        if any((row.get("status") == "succeeded") for row in rows):
            done = True
            break
        time.sleep(0.05)
    assert done, "job did not finish in time"


def test_ui_scenarios_run_bad_requests():
    c = TestClient(app)
    sid = db.create_scenario(name="ScB", parent_id=None, tag=None, description=None)
    # 存在しない config_id
    r = c.post(f"/ui/scenarios/{sid}/run", data={"config_id": 9999})
    assert r.status_code == 404
    # 不正な config JSON
    cfg_id_bad = db.create_config(name="CfgBad", json_text="invalid-json")
    r = c.post(f"/ui/scenarios/{sid}/run", data={"config_id": cfg_id_bad})
    assert r.status_code == 400

