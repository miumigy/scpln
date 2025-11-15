import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import db
from main import app
from app.metrics import (
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
)
from core.plan_repository import PlanRepository
from core.plan_repository_builders import (
    attach_inventory_to_detail_series,
    build_plan_series,
    build_plan_series_from_plan_final,
)
from core.config.storage import create_planning_input_set

pytestmark = pytest.mark.slow


def _make_plan_with_artifacts(version_id: str) -> None:
    # Use integrated run API to generate artifacts to keep parity with E2E
    client = TestClient(app)
    r = client.post(
        "/plans/create_and_execute",
        json={
            "version_id": version_id,
            "config_version_id": 100,
            "weeks": 4,
            "round_mode": "int",
            "lt_unit": "day",
            "lightweight": False,
        },
        timeout=120,
    )
    assert r.status_code == 200, r.text
    repo = PlanRepository(
        db._conn,
        PLAN_DB_WRITE_LATENCY,
        PLAN_SERIES_ROWS_TOTAL,
        PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    )
    assert repo.fetch_plan_series(
        version_id, "aggregate"
    ), "PlanRepositoryにaggregate行が存在すること"
    assert repo.fetch_plan_series(
        version_id, "det"
    ), "PlanRepositoryにdet行が存在すること"


def test_schedule_csv_and_ui_tabs_present(seed_canonical_data, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    client = TestClient(app)
    ver = f"uitabs-{int(time.time())}"
    _make_plan_with_artifacts(ver)
    # schedule.csv should be downloadable and include headers
    r = client.get(f"/plans/{ver}/schedule.csv")
    assert r.status_code == 200
    body = r.text.splitlines()
    assert body and body[0].startswith(
        "week,sku,scheduled_receipts,on_hand_start,on_hand_end"
    )
    # plan detail UI renders core tabs and links
    r = client.get(f"/ui/plans/{ver}")
    assert r.status_code == 200
    html = r.text
    for key in ("Aggregate", "Disaggregate", "Schedule", "Validate"):
        assert key in html
    # schedule.csv link should exist on the page
    assert f"/plans/{ver}/schedule.csv" in html


def test_state_management_round_trip(seed_canonical_data, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    client = TestClient(app)
    ver = f"state-{int(time.time())}"
    _make_plan_with_artifacts(ver)
    # advance to aggregated
    r = client.post(f"/ui/plans/{ver}/state/advance", data={"to": "aggregated"})
    assert r.status_code in (200, 303)
    # fetch UI and confirm state reflected
    r = client.get(f"/ui/plans/{ver}")
    assert r.status_code == 200
    assert "aggregated" in r.text


def test_metrics_include_planning_hub_counters():
    client = TestClient(app)
    r = client.get("/metrics")
    assert r.status_code == 200
    text = r.text
    # HELP 行（定義）が含まれていることを確認（ゼロ値でもエクスポートされる）
    for metric in (
        "plans_created_total",
        "plans_reconciled_total",
        "plans_viewed_total",
        "runs_queued_total",
        "plan_schedule_export_total",
        "plan_compare_export_total",
        "plan_carryover_export_total",
    ):
        assert ("# HELP " + metric) in text


def test_ui_plan_delete_flow(seed_canonical_data, monkeypatch):
    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    client = TestClient(app)
    version_id = f"ui-del-{int(time.time())}"
    _make_plan_with_artifacts(version_id)

    resp = client.post(
        f"/ui/plans/{version_id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers.get("location") == "/ui/plans"

    assert db.get_plan_version(version_id) is None
    assert db.get_plan_artifact(version_id, "plan_final.json") is None


def test_disagg_tab_prefers_plan_repository_rows(db_setup, monkeypatch):
    from app.ui_plans import ui_plan_detail

    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    version_id = f"ui-disagg-{int(time.time())}"
    db.create_plan_version(version_id, status="active", config_version_id=100)

    aggregate = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "demand": 25,
                "supply": 5,
                "backlog": 0,
            }
        ]
    }
    detail = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "sku": "SKU1",
                "week": "2025-01-W1",
                "demand": 25,
                "supply": 5,
                "backlog": 0,
            }
        ]
    }
    plan_final = {
        "rows": [
            {
                "item": "SKU1",
                "week": "2025-01-W1",
                "gross_req": 25,
                "scheduled_receipts": 0,
                "on_hand_start": 12.5,
                "net_req": 5,
                "planned_order_receipt": 20,
                "planned_order_release": 18,
                "planned_order_receipt_adj": 20,
                "planned_order_release_adj": 18,
                "on_hand_end": 7.5,
                "lt_weeks": 2,
                "lot": 1,
                "moq": 0,
            }
        ]
    }

    repo = PlanRepository(db._conn)
    series_rows = build_plan_series(version_id, aggregate=aggregate, detail=detail)
    attach_inventory_to_detail_series(series_rows, plan_final)
    series_rows.extend(build_plan_series_from_plan_final(version_id, plan_final))
    repo.write_plan(version_id, series=series_rows, kpis=[])

    db.upsert_plan_artifact(
        version_id,
        "aggregate.json",
        json.dumps(aggregate, ensure_ascii=False),
    )
    db.upsert_plan_artifact(
        version_id,
        "sku_week.json",
        json.dumps({"rows": detail["rows"]}, ensure_ascii=False),
    )

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = ui_plan_detail(version_id, request)
    disagg_rows = response.context["disagg_rows"]
    assert disagg_rows, "Disagg rows should exist"
    assert disagg_rows[0]["on_hand_start"] == 12.5
    assert disagg_rows[0]["lt_weeks"] == 2
    assert disagg_rows[0]["planned_release_adj"] == 18
    assert disagg_rows[0]["supply_plan"] == 20


def test_plan_detail_shows_planning_input_set_info(seed_canonical_data, monkeypatch):
    from app.ui_plans import ui_plan_detail

    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    label = f"inputset-{int(time.time())}"
    version_id = f"plan-isi-{int(time.time())}"
    create_planning_input_set(
        config_version_id=100,
        label=label,
        status="ready",
        source="ui",
    )
    db.create_plan_version(
        version_id,
        status="draft",
        config_version_id=100,
        input_set_label=label,
    )

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = ui_plan_detail(version_id, request)
    isi = response.context["input_set_info"]
    assert isi["label"] == label
    assert isi["status"] == "ready"
    assert isi["legacy"] is False
    assert isi["missing"] is False
    assert isi["inferred"] is False
    assert isi["config_version_id"] == 100


def test_plan_detail_infers_input_set_when_label_missing(
    seed_canonical_data, monkeypatch
):
    from app.ui_plans import ui_plan_detail

    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    label = f"inputset-{int(time.time())}"
    version_id = f"plan-isi-infer-{int(time.time())}"
    create_planning_input_set(
        config_version_id=100,
        label=label,
        status="ready",
        source="ui",
    )
    db.create_plan_version(
        version_id,
        status="draft",
        config_version_id=100,
        input_set_label=None,
    )

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = ui_plan_detail(version_id, request)
    isi = response.context["input_set_info"]
    assert isi["label"] == label
    assert isi["legacy"] is False
    assert isi["inferred"] is True
    assert isi["status"] == "ready"


def test_plan_detail_planning_inputs_summary_counts(db_setup, monkeypatch):
    from app.ui_plans import ui_plan_detail

    monkeypatch.setenv("REGISTRY_BACKEND", "db")
    monkeypatch.setenv("AUTH_MODE", "none")
    version_id = f"plan-agg-{int(time.time())}"
    db.create_plan_version(version_id, status="draft", config_version_id=100)

    plan_final = {"rows": [], "inputs_summary": {}}
    planning_inputs = {
        "schema_version": "planning_inputs-1",
        "demand_family": [{"family": "F1"}],
        "capacity": [{"resource": "R1"}, {"resource": "R2"}],
        "mix_share": [{"sku": "SKU1"}],
        "item_master": [{"sku": "SKU1"}, {"sku": "SKU2"}, {"sku": "SKU3"}],
        "inventory": [{"sku": "SKU1"}],
        "open_po": [{"sku": "SKU1"}, {"sku": "SKU2"}],
    }
    db.upsert_plan_artifact(
        version_id, "plan_final.json", json.dumps(plan_final, ensure_ascii=False)
    )
    db.upsert_plan_artifact(
        version_id,
        "planning_inputs.json",
        json.dumps(planning_inputs, ensure_ascii=False),
    )

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = ui_plan_detail(version_id, request)
    summary = response.context["planning_summary"]
    assert summary["schema_version"] == "planning_inputs-1"
    assert summary["demand_family"] == 1
    assert summary["capacity"] == 2
    assert summary["mix_share"] == 1
    assert summary["item_master"] == 3
    assert summary["inventory"] == 1
    assert summary["open_po"] == 2
