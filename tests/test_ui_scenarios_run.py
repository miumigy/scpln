import importlib
import time
import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from alembic.config import Config
from alembic import command

# 有効化
importlib.import_module("app.ui_scenarios")
importlib.import_module("app.jobs_api")
importlib.import_module("app.simulation_api")


@pytest.fixture(name="db_setup_scenarios")
def db_setup_scenarios_fixture(tmp_path: Path):
    db_path = tmp_path / "test_scenarios.sqlite"
    os.environ["SCPLN_DB"] = str(db_path)
    os.environ["REGISTRY_BACKEND"] = "db"
    os.environ["AUTH_MODE"] = "none"

    # Reload app.db to pick up new SCPLN_DB env var
    importlib.reload(importlib.import_module("app.db"))
    importlib.reload(importlib.import_module("app.plans_api"))
    importlib.reload(importlib.import_module("app.config_api"))
    importlib.reload(importlib.import_module("app.scenario_api"))
    importlib.reload(importlib.import_module("main"))

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("script_location", "alembic")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")

    yield

    del os.environ["SCPLN_DB"]
    del os.environ["REGISTRY_BACKEND"]
    del os.environ["AUTH_MODE"]


def test_ui_scenarios_run_with_config(db_setup_scenarios):
    from app.api import app
    from app import db

    c = TestClient(app)
    # 準備: シナリオと設定を作成
    sid = db.create_scenario(name="ScA", parent_id=None, tag=None, description=None)
    cfg_json = {
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
    cfg_id = db.create_config(
        name="CfgA",
        json_text=(
            db.json_dumps(cfg_json)
            if hasattr(db, "json_dumps")
            else __import__("json").dumps(cfg_json, ensure_ascii=False)
        ),
    )

    # 実行: UI経由でRun（ジョブ投入）
    r = c.post(
        f"/ui/scenarios/{sid}/run", data={"config_id": cfg_id}, follow_redirects=False
    )
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


def test_ui_scenarios_run_nonexistent_config(db_setup_scenarios):
    from app.api import app
    from app import db

    c = TestClient(app)
    # 存在しない config_id を使って404が返ることを確認
    sid = db.create_scenario(
        name="Sc-nonexistent", parent_id=None, tag=None, description=None
    )
    # テスト用のIDが他のテストと衝突しないように、また確実に存在しないようにする
    test_config_id = 99999
    try:
        db.delete_config(test_config_id)
        r = c.post(
            f"/ui/scenarios/{sid}/run",
            data={"config_id": test_config_id},
            follow_redirects=False,
        )
        assert r.status_code == 404
    finally:
        db.delete_scenario(sid)


def test_ui_scenarios_run_invalid_config_json(db_setup_scenarios):
    from app.api import app
    from app import db

    c = TestClient(app)
    # 不正なJSONを持つconfigで400が返ることを確認
    sid = db.create_scenario(
        name="Sc-invalid", parent_id=None, tag=None, description=None
    )
    cfg_id_bad = -1
    try:
        cfg_id_bad = db.create_config(name="CfgBad", json_text="invalid-json")
        r = c.post(
            f"/ui/scenarios/{sid}/run",
            data={"config_id": cfg_id_bad},
            follow_redirects=False,
        )
        assert r.status_code == 400
    finally:
        db.delete_scenario(sid)
        if cfg_id_bad != -1:
            db.delete_config(cfg_id_bad)
