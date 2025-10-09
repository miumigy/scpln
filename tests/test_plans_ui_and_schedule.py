import time
from fastapi.testclient import TestClient

from app import db
from main import app
from app.metrics import (
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
)
from core.plan_repository import PlanRepository


def _make_plan_with_artifacts(version_id: str) -> None:
    # Use integrated run API to generate artifacts to keep parity with E2E
    client = TestClient(app)
    r = client.post(
        "/plans/integrated/run",
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
