from __future__ import annotations

import time
import os
import pytest
import importlib
from pathlib import Path
from fastapi.testclient import TestClient

from alembic.config import Config
from alembic import command


@pytest.fixture(name="db_setup_auto_plan")
def db_setup_auto_plan_fixture(tmp_path: Path):
    db_path = tmp_path / "test_auto_plan.sqlite"
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


def test_plan_run_auto_redirects_to_new_plan(db_setup_auto_plan):
    from main import app

    client = TestClient(app)
    base = f"base-{int(time.time())}"
    # まずベースのPlanを作って詳細画面を有効化
    r = client.post(
        "/plans/integrated/run",
        json={
            "version_id": base,
            "input_dir": "samples/planning",
            "weeks": 4,
            "round_mode": "int",
            "lt_unit": "day",
        },
        timeout=120,
    )
    assert r.status_code == 200
    # Plan & Run（自動補完）を叩く（anchor/tol付き）
    r2 = client.post(
        f"/ui/plans/{base}/plan_run_auto",
        data={
            "input_dir": "samples/planning",
            "weeks": "4",
            "lt_unit": "day",
            "cutover_date": "2025-01-15",
            "anchor_policy": "blend",
            "tol_abs": "1e-6",
            "tol_rel": "1e-6",
        },
    )
    # TestClientはデフォルトでリダイレクトを追跡するため、最終的に詳細画面が200で開ける
    assert r2.status_code == 200
    assert "Plan Detail" in r2.text
