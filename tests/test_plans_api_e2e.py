from __future__ import annotations

import time
import os
import pytest
import importlib
from pathlib import Path
from fastapi.testclient import TestClient

from alembic.config import Config
from alembic import command


@pytest.fixture(name="db_setup_e2e")
def db_setup_e2e_fixture(tmp_path: Path):
    db_path = tmp_path / "test_e2e.sqlite"
    os.environ["SCPLN_DB"] = str(db_path)
    os.environ["REGISTRY_BACKEND"] = "db"
    os.environ["AUTH_MODE"] = "none"

    # Reload app.db to pick up new SCPLN_DB env var
    importlib.reload(importlib.import_module("app.db"))
    importlib.reload(importlib.import_module("app.plans_api"))

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("script_location", "alembic")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")

    yield

    del os.environ["SCPLN_DB"]
    del os.environ["REGISTRY_BACKEND"]
    del os.environ["AUTH_MODE"]


def test_plans_integrated_run_and_reconcile_e2e(db_setup_e2e):
    from main import app

    client = TestClient(app)
    ver = f"testv-{int(time.time())}"
    # integrated run
    r = client.post(
        "/plans/integrated/run",
        json={
            "version_id": ver,
            "input_dir": "samples/planning",
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
