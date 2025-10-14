import time
from fastapi.testclient import TestClient


def test_plan_run_auto_redirects_to_new_plan(seed_canonical_data, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")

    from main import app

    client = TestClient(app)
    base = f"base-{int(time.time())}"
    # まずベースのPlanを作って詳細画面を有効化
    r = client.post(
        "/plans/create_and_execute",
        json={
            "version_id": base,
            "config_version_id": 100,
            "weeks": 4,
            "round_mode": "int",
            "lt_unit": "day",
            "lightweight": True,
        },
        timeout=120,
    )
    assert r.status_code == 200
    # Plan & Run（自動補完）を叩く（anchor/tol付き）
    r2 = client.post(
        f"/ui/plans/{base}/execute_auto",
        data={
            "weeks": "4",
            "lt_unit": "day",
            "cutover_date": "2025-01-15",
            "anchor_policy": "blend",
            "tol_abs": "1e-6",
            "tol_rel": "1e-6",
            "lightweight": "1",
        },
    )
    # TestClientはデフォルトでリダイレクトを追跡するため、最終的に詳細画面が200で開ける
    assert r2.status_code == 200
    assert "Plan Detail" in r2.text
