import importlib
import time
from fastapi.testclient import TestClient
from app import db

importlib.import_module("app.simulation_api")
importlib.import_module("app.jobs_api")
importlib.import_module("app.run_compare_api")

from app.api import app


def test_rbac_blocks_simulation_without_role(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "1")
    c = TestClient(app)
    payload = {
        "planning_horizon": 1,
        "products": [{"name": "P1", "sales_price": 1}],
        "nodes": [{"node_type": "store", "name": "S1", "initial_stock": {"P1": 0}}],
        "network": [],
        "customer_demand": [{"store_name": "S1", "product_name": "P1", "demand_mean": 0, "demand_std_dev": 0}],
    }
    r = c.post("/simulation", json=payload)
    assert r.status_code == 403


def test_rbac_allows_simulation_with_role_and_org_tenant(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "1")
    monkeypatch.setenv("RBAC_MUTATE_ROLES", "planner,admin")
    c = TestClient(app)
    payload = {
        "planning_horizon": 1,
        "products": [{"name": "P1", "sales_price": 1}],
        "nodes": [{"node_type": "store", "name": "S1", "initial_stock": {"P1": 0}}],
        "network": [],
        "customer_demand": [{"store_name": "S1", "product_name": "P1", "demand_mean": 0, "demand_std_dev": 0}],
    }
    r = c.post(
        "/simulation",
        json=payload,
        headers={"X-Role": "planner", "X-Org-ID": "org1", "X-Tenant-ID": "t1"},
    )
    assert r.status_code == 200


def test_rbac_blocks_jobs_without_role(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "1")
    c = TestClient(app)
    r = c.post("/jobs/simulation", json={})
    assert r.status_code == 403
    r2 = c.post("/jobs/aggregate", json={})
    assert r2.status_code == 403


def test_rbac_allows_jobs_with_role_and_org_tenant(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "1")
    monkeypatch.setenv("RBAC_MUTATE_ROLES", "planner,admin")
    c = TestClient(app)
    payload = {
        "planning_horizon": 1,
        "products": [{"name": "P1", "sales_price": 1}],
        "nodes": [{"node_type": "store", "name": "S1", "initial_stock": {"P1": 0}}],
        "network": [],
        "customer_demand": [{"store_name": "S1", "product_name": "P1", "demand_mean": 0, "demand_std_dev": 0}],
    }
    r = c.post(
        "/jobs/simulation",
        json=payload,
        headers={"X-Role": "admin", "X-Org-ID": "org1", "X-Tenant-ID": "t1"},
    )
    assert r.status_code == 200

def test_rbac_blocks_job_actions_without_role(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "1")
    c = TestClient(app)
    # 事前にDBに直接ジョブを作成
    job_id = "test-job-for-retry-blocked"
    db.create_job(job_id, "simulation", "failed", int(time.time() * 1000), "{}")
    r_retry = c.post(f"/jobs/{job_id}/retry")
    assert r_retry.status_code == 403
    job_id_2 = "test-job-for-cancel-blocked"
    db.create_job(job_id_2, "simulation", "queued", int(time.time() * 1000), "{}")
    r_cancel = c.post(f"/jobs/{job_id_2}/cancel")
    assert r_cancel.status_code == 403

def test_rbac_allows_job_actions_with_role(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "1")
    monkeypatch.setenv("RBAC_MUTATE_ROLES", "planner")
    c = TestClient(app)
    headers = {"X-Role": "planner", "X-Org-ID": "org1", "X-Tenant-ID": "t1"}
    # 事前にDBに直接ジョブを作成
    job_id = "test-job-for-retry"
    db.create_job(job_id, "simulation", "failed", int(time.time() * 1000), "{}")
    r_retry = c.post(f"/jobs/{job_id}/retry", headers=headers)
    assert r_retry.status_code == 200
    # cancelのテストも同様に修正
    job_id_2 = "test-job-for-cancel"
    db.create_job(job_id_2, "simulation", "queued", int(time.time() * 1000), "{}")
    r_cancel = c.post(f"/jobs/{job_id_2}/cancel", headers=headers)
    assert r_cancel.status_code == 200


def test_rbac_blocks_delete_run_without_role(monkeypatch):
    monkeypatch.setenv("RBAC_DELETE_ENABLED", "1")
    c = TestClient(app)
    # 事前に実行結果を作成
    run_id = "test-run-for-delete"
    from app.run_registry import REGISTRY
    REGISTRY.put(run_id, {"summary": {}})
    r = c.delete(f"/runs/{run_id}")
    assert r.status_code == 403
    # クリーンアップ
    REGISTRY.delete(run_id)
    monkeypatch.setenv("RBAC_DELETE_ENABLED", "0")


def test_rbac_allows_delete_run_with_role(monkeypatch):
    monkeypatch.setenv("RBAC_DELETE_ENABLED", "1")
    monkeypatch.setenv("RBAC_DELETE_ROLES", "admin")
    c = TestClient(app)
    headers = {"X-Role": "admin"}
    # 事前に実行結果を作成
    run_id = "test-run-for-delete-2"
    from app.run_registry import REGISTRY
    REGISTRY.put(run_id, {"summary": {}})
    r = c.delete(f"/runs/{run_id}", headers=headers)
    assert r.status_code == 200
    # 存在しないことの確認
    assert REGISTRY.get(run_id) == {}
    monkeypatch.setenv("RBAC_DELETE_ENABLED", "0")

