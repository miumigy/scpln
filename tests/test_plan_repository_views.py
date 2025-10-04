from app import db
from core.plan_repository import PlanRepository
from core.plan_repository_builders import build_plan_series
from core.plan_repository_views import fetch_aggregate_rows, fetch_detail_rows


def test_plan_repository_view_helpers(db_setup):
    repo = PlanRepository(db._conn)
    version_id = "plan-view-001"
    db.create_plan_version(version_id, status="active")

    aggregate = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "demand": 100,
                "supply": 90,
                "backlog": 10,
                "capacity_total": 120,
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
                "supply": 20,
                "backlog": 5,
            }
        ]
    }

    series_rows = build_plan_series(version_id, aggregate=aggregate, detail=detail)
    repo.write_plan(version_id, series=series_rows, kpis=[])

    agg_rows = fetch_aggregate_rows(repo, version_id)
    assert agg_rows
    assert agg_rows[0]["family"] == "F1"
    assert agg_rows[0]["period"] == "2025-01"

    det_rows = fetch_detail_rows(repo, version_id)
    assert det_rows
    assert det_rows[0]["sku"] == "SKU1"
    assert det_rows[0]["week"] == "2025-01-W1"
