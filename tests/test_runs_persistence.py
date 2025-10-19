import json
import os
import time
import importlib
from pathlib import Path

import pytest
import sqlite3

from alembic.config import Config
from alembic import command

from app import db as appdb
from app.run_registry_db import RunRegistryDB

pytestmark = pytest.mark.slow


def _prepare_db(tmp_path: Path) -> str:
    db_path = tmp_path / "runs.sqlite"
    os.environ["SCPLN_DB"] = str(db_path)
    os.environ["REGISTRY_BACKEND"] = "db"
    os.environ["AUTH_MODE"] = "none"

    # reset cached path used by app.db
    appdb._current_db_path = str(db_path)

    # ensure modules pick up new env/config if already imported
    for module in ("app.run_registry", "app.run_registry_db"):
        if module in list(importlib.sys.modules.keys()):
            importlib.reload(importlib.import_module(module))

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
    return str(db_path)


def _sample_payload(run_id: str, *, started_at: int) -> dict:
    return {
        "run_id": run_id,
        "started_at": started_at,
        "duration_ms": 5,
        "schema_version": "1.0",
        "summary": {"fill_rate": 1.0, "_plan_version_id": "plan-from-" + run_id},
        "results": [],
        "daily_profit_loss": [],
        "cost_trace": [],
        "config_version_id": None,
        "scenario_id": None,
        "config_json": None,
        "plan_version_id": "plan-from-" + run_id,
    }


def test_runs_persist_db_backend(tmp_path: Path):
    db_path = _prepare_db(tmp_path)
    registry = RunRegistryDB()

    run_id = "run-test-1"
    payload = _sample_payload(run_id, started_at=int(time.time() * 1000))
    registry.put(run_id, payload)

    # registry.get should return the stored payload
    rec = registry.get(run_id)
    assert rec
    assert rec.get("run_id") == run_id
    assert rec.get("summary", {}).get("fill_rate") == 1.0
    assert rec.get("plan_version_id") == "plan-from-" + run_id

    # verify persistence at DB level
    conn = sqlite3.connect(db_path)
    with conn:
        row = conn.execute(
            "SELECT run_id, summary, plan_version_id FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == run_id
        summary_obj = json.loads(row[1] or "{}")
        assert summary_obj.get("_plan_version_id") == "plan-from-" + run_id
        assert row[2] == "plan-from-" + run_id


def test_runs_cleanup_capacity(tmp_path: Path):
    os.environ["RUNS_DB_MAX_ROWS"] = "2"
    db_path = _prepare_db(tmp_path)
    registry = RunRegistryDB()

    timestamps = [int(time.time() * 1000) + i for i in range(3)]
    run_ids = []
    for idx, ts in enumerate(timestamps):
        run_id = f"run-{idx}"
        registry.put(run_id, _sample_payload(run_id, started_at=ts))
        run_ids.append(run_id)

    rows = registry.list()
    kept_ids = [row.get("run_id") for row in rows]
    assert len(kept_ids) == 2
    assert run_ids[0] not in kept_ids
    assert set(run_ids[1:]) <= set(kept_ids)

    conn = sqlite3.connect(db_path)
    with conn:
        count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert count == 2
        summaries = [
            json.loads(row[0] or "{}")
            for row in conn.execute("SELECT summary FROM runs").fetchall()
        ]
        assert all("_plan_version_id" in s for s in summaries)
        plan_versions = [
            row[0]
            for row in conn.execute("SELECT plan_version_id FROM runs").fetchall()
        ]
        assert len(plan_versions) == 2
        assert all(pv and pv.startswith("plan-from-") for pv in plan_versions)
