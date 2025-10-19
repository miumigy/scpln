import pytest
from fastapi.testclient import TestClient

from app import db

pytestmark = pytest.mark.slow


def test_ui_scenarios_run_returns_403(monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    db.init_db(force=True)

    from app.api import app

    c = TestClient(app)
    sid = db.create_scenario(name="ScA", parent_id=None, tag=None, description=None)
    try:
        r = c.post(
            f"/ui/scenarios/{sid}/run", data={"config_id": 1}, follow_redirects=False
        )
        assert r.status_code == 403
        assert "Plan & Execute" in (r.text or "")
    finally:
        db.delete_scenario(sid)
