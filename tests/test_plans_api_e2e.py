import time
from fastapi.testclient import TestClient


def test_plans_integrated_run_and_reconcile_e2e(seed_canonical_data, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")

    from main import app

    client = TestClient(app)
    ver = f"testv-{int(time.time())}"
    # integrated run
    r = client.post(
        "/plans/integrated/run",
        json={
            "version_id": ver,
            "config_version_id": 100,
            "weeks": 4,
            "round_mode": "int",
            "lt_unit": "day",
            "cutover_date": "2025-01-15",
            "anchor_policy": "blend",
            "apply_adjusted": False,
        },
        timeout=120,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("version_id") == ver
    # list
    r = client.get("/plans")
    assert r.status_code == 200
    assert any(p.get("version_id") == ver for p in r.json().get("plans", []))
    # summary
    r = client.get(f"/plans/{ver}/summary")
    assert r.status_code == 200
    # reconcile (before only)
    r = client.post(f"/plans/{ver}/reconcile", json={"tol_abs": 1e-6, "tol_rel": 1e-6})
    assert r.status_code == 200
    assert r.json().get("version_id") == ver
