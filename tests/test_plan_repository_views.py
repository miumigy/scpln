from app import db
from core.plan_repository import PlanRepository
from core.plan_repository_builders import (
    build_plan_series,
    build_plan_series_from_plan_final,
    build_plan_series_from_weekly_summary,
)
from core.plan_repository_views import (
    build_plan_summaries,
    fetch_aggregate_rows,
    fetch_detail_rows,
)


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
    plan_final = {
        "rows": [
            {
                "item": "SKU1",
                "week": "2025-01-W1",
                "gross_req": 25,
                "scheduled_receipts": 2,
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

    series_rows = build_plan_series(version_id, aggregate=aggregate, detail=detail)
    series_rows.extend(build_plan_series_from_plan_final(version_id, plan_final))
    repo.write_plan(version_id, series=series_rows, kpis=[])

    agg_rows = fetch_aggregate_rows(repo, version_id)
    assert agg_rows
    assert agg_rows[0]["family"] == "F1"
    assert agg_rows[0]["period"] == "2025-01"

    det_rows = fetch_detail_rows(repo, version_id)
    assert det_rows
    assert det_rows[0]["sku"] == "SKU1"
    assert det_rows[0]["week"] == "2025-01-W1"
    assert det_rows[0]["on_hand_start"] == 12.5
    assert det_rows[0]["on_hand_end"] == 7.5


def test_build_plan_summaries_fallback_kpi(db_setup):
    repo = PlanRepository(db._conn)
    version_id = "plan-summary-001"
    db.create_plan_version(version_id, status="active")

    aggregate = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "demand": 100,
                "supply": 110,
                "backlog": 5,
            }
        ]
    }
    plan_final = {
        "rows": [
            {
                "item": "SKU1",
                "week": "2025-01-W1",
                "gross_req": 25,
                "scheduled_receipts": 2,
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
        ],
        "weekly_summary": [
            {
                "week": "2025-01-W1",
                "capacity": 50,
                "original_load": 25,
                "adjusted_load": 20,
                "spill_out": 5,
            }
        ],
    }

    series_rows = build_plan_series(version_id, aggregate=aggregate, detail=None)
    series_rows.extend(build_plan_series_from_plan_final(version_id, plan_final))
    series_rows.extend(build_plan_series_from_weekly_summary(version_id, plan_final))
    repo.write_plan(version_id, series=series_rows, kpis=[])

    summaries = build_plan_summaries(repo, [version_id], include_kpi=True)
    assert version_id in summaries
    kpi = summaries[version_id].get("kpi") or {}
    assert kpi.get("fill_rate") == 1.1
    assert kpi.get("backlog_days") is not None and kpi["backlog_days"] > 0
