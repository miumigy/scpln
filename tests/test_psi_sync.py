from __future__ import annotations

import importlib
from typing import Any
from uuid import uuid4
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient


def _reload_for_tmp_db(db_path: Path):
    """Reload DBと主要APIモジュールをテンポラリDB向けに初期化。"""
    app_db = importlib.import_module("app.db")
    app_api = importlib.import_module("app.api")
    importlib.reload(app_db)
    app_api = importlib.reload(app_api)

    module_names = [
        "app.__init__",
        "app.simulation_api",
        "app.jobs_api",
        "app.hierarchy_api",
        "app.config_api",
        "app.scenario_api",
        "app.run_compare_api",
        "app.plans_api",
        "app.run_meta_api",
        "app.runs_api",
        "app.run_list_api",
        "app.trace_export_api",
        "app.ui_plans",
        "app.ui_runs",
        "app.ui_compare",
        "app.ui_jobs",
        "app.ui_scenarios",
        "app.ui_configs",
        "app.ui_hierarchy",
    ]
    reloaded: dict[str, Any] = {}
    for name in module_names:
        try:
            mod = importlib.import_module(name)
            reloaded[name] = importlib.reload(mod)
        except ModuleNotFoundError:
            pass

    main_mod = importlib.import_module("main")
    importlib.reload(main_mod)

    # Alembicでマイグレーションを実行
    alembic_ini_path = Path(__file__).parent.parent / "alembic.ini"
    tmp_path = db_path.parent
    temp_alembic_ini_path = tmp_path / "alembic.ini"
    
    with open(alembic_ini_path, "r") as src, open(temp_alembic_ini_path, "w") as dst:
        for line in src:
            if line.strip().startswith("sqlalchemy.url"):
                dst.write(f"sqlalchemy.url = sqlite:///{db_path}\n")
            else:
                dst.write(line)

    old_sys_argv = sys.argv
    try:
        sys.argv = ["alembic", "-c", str(temp_alembic_ini_path), "upgrade", "head"]
        from alembic.config import main as alembic_main
        alembic_main()
    finally:
        sys.argv = old_sys_argv

    app_plans_api = reloaded.get("app.plans_api") or importlib.import_module(
        "app.plans_api"
    )
    return app_db, app_plans_api, app_api


@pytest.fixture()
def plan_client(tmp_path, monkeypatch):
    db_path = tmp_path / "scpln.db"
    monkeypatch.setenv("SCPLN_DB", str(db_path))
    app_db, app_plans_api, app_api = _reload_for_tmp_db(db_path)
    client = TestClient(app_api.app)
    version = f"test-{uuid4().hex[:8]}"
    try:
        res = client.post(
            "/plans/integrated/run",
            json={
                "version_id": version,
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
        assert res.status_code == 200, res.text
        yield client, version, app_db, app_plans_api
    finally:
        client.close()

def _load_rows(db_mod, version_id: str, name: str) -> list[dict]:
    data = db_mod.get_plan_artifact(version_id, name)
    assert data, f"missing artifact {name}"
    return data.get("rows", [])


def _apply(level: str, rows: list[dict], overlay_rows: list[dict], plans_api_mod):
    return plans_api_mod._apply_overlay(level, rows, overlay_rows)  # type: ignore[attr-defined]


def _match_group(row: dict, period: str, family: str, plans_api_mod) -> bool:
    if str(row.get("family")) != family:
        return False
    per_det = row.get("period")
    if per_det is not None and str(per_det) == period:
        return True
    week = row.get("week")
    if week is None:
        return False
    week_s = str(week)
    if week_s == period:
        return True
    return plans_api_mod._week_to_month(week_s) == period  # type: ignore[attr-defined]


def _sum_detail(rows: list[dict], period: str, family: str, plans_api_mod):
    demand = 0.0
    supply = 0.0
    backlog = 0.0
    for r in rows:
        if not _match_group(r, period, family, plans_api_mod):
            continue
        demand += float(r.get("demand") or 0.0)
        if r.get("supply_plan") is not None:
            supply += float(r.get("supply_plan") or 0.0)
        else:
            supply += float(r.get("supply") or 0.0)
        backlog += float(r.get("backlog") or 0.0)
    return demand, supply, backlog


def test_detail_edit_rolls_up_to_aggregate(plan_client):
    client, version, db_mod, plans_api_mod = plan_client
    det_rows = _load_rows(db_mod, version, "sku_week.json")
    agg_rows = _load_rows(db_mod, version, "aggregate.json")
    target = next(
        r for r in det_rows if r.get("family") and r.get("period") and r.get("week")
    )
    period = str(target["period"])
    family = str(target["family"])
    new_demand = float(target.get("demand") or 0.0) + 11.0
    base_supply = float(target.get("supply_plan") or target.get("supply") or 0.0)
    new_supply = base_supply + 7.0
    base_backlog = float(target.get("backlog") or 0.0)
    new_backlog = base_backlog + 3.0
    resp = client.patch(
        f"/plans/{version}/psi",
        json={
            "level": "det",
            "edits": [
                {
                    "key": {"week": target["week"], "sku": target["sku"]},
                    "fields": {
                        "demand": new_demand,
                        "supply_plan": new_supply,
                        "backlog": new_backlog,
                    },
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text

    overlay = db_mod.get_plan_artifact(version, "psi_overrides.json")
    assert overlay, "overlay should be stored"
    det_final = _apply("det", det_rows, overlay.get("det") or [], plans_api_mod)
    agg_final = _apply(
        "aggregate", agg_rows, overlay.get("aggregate") or [], plans_api_mod
    )
    sum_demand, sum_supply, sum_backlog = _sum_detail(
        det_final, period, family, plans_api_mod
    )
    agg_row = next(
        r
        for r in agg_final
        if str(r.get("period")) == period and str(r.get("family")) == family
    )
    assert agg_row.get("demand") == pytest.approx(sum_demand, rel=1e-6, abs=1e-6)
    assert agg_row.get("supply") == pytest.approx(sum_supply, rel=1e-6, abs=1e-6)
    assert agg_row.get("backlog") == pytest.approx(sum_backlog, rel=1e-6, abs=1e-6)
    assert any(
        str(r.get("period")) == period and str(r.get("family")) == family
        for r in overlay.get("aggregate") or []
    )


def test_aggregate_edit_distributes_to_detail(plan_client):
    client, version, db_mod, plans_api_mod = plan_client
    det_rows = _load_rows(db_mod, version, "sku_week.json")
    agg_rows = _load_rows(db_mod, version, "aggregate.json")
    target = next(r for r in agg_rows if r.get("family") and r.get("period"))
    period = str(target["period"])
    family = str(target["family"])
    new_demand = float(target.get("demand") or 0.0) + 25.0
    new_supply = float(target.get("supply") or 0.0) + 12.0
    new_backlog = float(target.get("backlog") or 0.0) + 5.0
    resp = client.patch(
        f"/plans/{version}/psi",
        json={
            "level": "aggregate",
            "edits": [
                {
                    "key": {"period": period, "family": family},
                    "fields": {
                        "demand": new_demand,
                        "supply": new_supply,
                        "backlog": new_backlog,
                    },
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text

    overlay = db_mod.get_plan_artifact(version, "psi_overrides.json")
    assert overlay, "overlay should exist"
    det_final = _apply("det", det_rows, overlay.get("det") or [], plans_api_mod)
    agg_final = _apply(
        "aggregate", agg_rows, overlay.get("aggregate") or [], plans_api_mod
    )
    sum_demand, sum_supply, sum_backlog = _sum_detail(
        det_final, period, family, plans_api_mod
    )
    agg_row = next(
        r
        for r in agg_final
        if str(r.get("period")) == period and str(r.get("family")) == family
    )
    assert agg_row.get("demand") == pytest.approx(new_demand, rel=1e-6, abs=1e-6)
    assert agg_row.get("supply") == pytest.approx(new_supply, rel=1e-6, abs=1e-6)
    assert agg_row.get("backlog") == pytest.approx(new_backlog, rel=1e-6, abs=1e-6)
    assert sum_demand == pytest.approx(new_demand, rel=1e-6, abs=1e-6)
    assert sum_supply == pytest.approx(new_supply, rel=1e-6, abs=1e-6)
    assert sum_backlog == pytest.approx(new_backlog, rel=1e-6, abs=1e-6)
    assert overlay.get("det") or [], "detail overlay should be populated"
