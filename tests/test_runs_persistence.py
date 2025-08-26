import json
import os
import time
from pathlib import Path
import importlib


def _load_default_input(root: Path) -> dict:
    p = root / "static" / "default_input.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _make_client_with_db(tmp_path: Path):
    # Set env before importing app
    db_path = tmp_path / "runs.sqlite"
    os.environ["SCPLN_DB"] = str(db_path)
    os.environ["REGISTRY_BACKEND"] = "db"
    os.environ["AUTH_MODE"] = "none"
    # Ensure modules pick up env
    for m in ("app.db", "app.run_registry", "app.run_registry_db", "main"):
        if m in list(importlib.sys.modules.keys()):
            importlib.reload(importlib.import_module(m))
    from main import app  # noqa
    from fastapi.testclient import TestClient

    client = TestClient(app)
    return client


def test_runs_persist_db_backend(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    client = _make_client_with_db(tmp_path)
    payload = _load_default_input(root)
    r = client.post("/simulation", json=payload)
    assert r.status_code == 200
    rid = r.json().get("run_id")
    assert rid

    # list runs (light)
    r2 = client.get("/runs")
    assert r2.status_code == 200
    body = r2.json()
    runs = body.get("runs") or []
    ids = [x.get("run_id") for x in runs]
    assert rid in ids

    # detail
    r3 = client.get(f"/runs/{rid}", params={"detail": True})
    assert r3.status_code == 200
    rec = r3.json()
    # persisted fields
    assert rec.get("run_id") == rid
    assert isinstance(rec.get("results"), list)


def test_runs_cleanup_capacity(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    # capacity = 2
    os.environ["RUNS_DB_MAX_ROWS"] = "2"
    client = _make_client_with_db(tmp_path)
    payload = _load_default_input(root)
    ids = []
    for _ in range(3):
        r = client.post("/simulation", json=payload)
        assert r.status_code == 200
        ids.append(r.json().get("run_id"))
        time.sleep(0.01)
    # list runs: only 2 newest should remain
    r2 = client.get("/runs")
    rows = r2.json().get("runs") or []
    got_ids = [x.get("run_id") for x in rows]
    assert len(got_ids) == 2
    # oldest removed
    assert ids[0] not in got_ids
    # newest two present (order may be desc)
    assert set(ids[1:]) <= set(got_ids)

