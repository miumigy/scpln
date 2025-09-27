from fastapi.testclient import TestClient

# 有効化
import importlib

importlib.import_module("app.ui_scenarios")
importlib.import_module("app.jobs_api")
importlib.import_module("app.simulation_api")

import pytest
from app import jobs, db
from prometheus_client import REGISTRY


@pytest.fixture
def job_manager_setup(db_setup):
    # Prometheus レジストリをクリア
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        REGISTRY.unregister(collector)

    manager = jobs.JobManager(workers=1, db_path=db_setup)
    original_manager = jobs.JOB_MANAGER
    if original_manager and original_manager is not manager:
        try:
            original_manager.stop()
        except Exception:
            pass
    previous_db_path = getattr(db, "_current_db_path", None)
    jobs.JOB_MANAGER = manager
    setattr(db, "_current_db_path", db_setup)
    manager.start()
    try:
        yield manager
    finally:
        manager.stop()
        jobs.JOB_MANAGER = original_manager
        setattr(db, "_current_db_path", previous_db_path)
        if original_manager and original_manager is not manager:
            try:
                original_manager.start()
            except Exception:
                pass


def test_ui_scenarios_run_with_config(job_manager_setup, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.setenv("SCPLN_ALLOW_LEGACY_SCENARIO_RUN", "1")

    from app.api import app

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
    job_rows = db.list_jobs(None, 0, 5).get("jobs", [])
    assert job_rows, "job not enqueued"
    job_id = job_rows[0]["job_id"]
    job_manager_setup._run_simulation(job_id)
    final = db.get_job(job_id)
    assert final and final.get("status") == "succeeded"


def test_ui_scenarios_run_nonexistent_config(job_manager_setup, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.setenv("SCPLN_ALLOW_LEGACY_SCENARIO_RUN", "1")

    from app.api import app

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


def test_ui_scenarios_run_invalid_config_json(job_manager_setup, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.setenv("SCPLN_ALLOW_LEGACY_SCENARIO_RUN", "1")

    from app.api import app

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
