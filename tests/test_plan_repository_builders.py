import json

from core.plan_repository_builders import (
    attach_inventory_to_detail_series,
    build_plan_kpis_from_aggregate,
    build_plan_series,
    build_plan_series_from_detail,
    build_plan_series_from_plan_final,
)


def test_build_plan_series_combines_levels():
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

    rows = build_plan_series("v-test", aggregate=aggregate, detail=detail)
    assert len(rows) == 2
    agg = next(r for r in rows if r["level"] == "aggregate")
    det = next(r for r in rows if r["level"] == "det")
    assert agg["time_bucket_type"] == "month"
    assert agg["time_bucket_key"] == "2025-01"
    assert agg["demand"] == 100.0
    assert det["item_key"] == "SKU1"
    assert det["time_bucket_type"] == "week"
    assert det["time_bucket_key"] == "2025-01-W1"


def test_build_plan_kpis_from_aggregate():
    aggregate = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "demand": 100,
                "supply": 90,
                "backlog": 10,
            },
            {
                "family": "F2",
                "period": "2025-01",
                "demand": 50,
                "supply": 50,
                "backlog": 0,
            },
            {
                "family": "F1",
                "period": "2025-02",
                "demand": 120,
                "supply": 100,
                "backlog": 20,
            },
        ]
    }

    kpis = build_plan_kpis_from_aggregate("v-test", aggregate)
    # month buckets + totals -> expect 6 entries (2 metrics * 2 months) + 4 totals = 8
    assert len(kpis) == 8
    month_kpi = next(
        r
        for r in kpis
        if r["metric"] == "fill_rate"
        and r["bucket_type"] == "month"
        and r["bucket_key"] == "2025-01"
    )
    assert round(month_kpi["value"], 4) == round((90 + 50) / (100 + 50), 4)
    total_backlog = next(
        r
        for r in kpis
        if r["metric"] == "backlog_total" and r["bucket_type"] == "total"
    )
    assert total_backlog["value"] == 30.0


def test_build_plan_series_from_detail_merges_duplicate_weeks():
    detail = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "sku": "SKU1",
                "week": "2025-W05",
                "demand": 5,
                "supply": 4,
                "backlog": 1,
            },
            {
                "family": "F1",
                "period": "2025-02",
                "sku": "SKU1",
                "week": "2025-W05",
                "demand": 3,
                "supply": 2,
                "backlog": 1,
            },
        ]
    }

    rows = build_plan_series_from_detail("v-test", detail)
    assert len(rows) == 1
    row = rows[0]
    assert row["time_bucket_key"] == "2025-W05"
    assert row["demand"] == 8.0
    assert row["supply"] == 6.0
    assert row["backlog"] == 2.0
    extra = json.loads(row["extra_json"])
    assert extra["period"] == "2025-01"
    assert "periods" in extra and extra["periods"] == ["2025-01", "2025-02"]


def test_build_plan_series_from_plan_final_inventory():
    plan_final = {
        "rows": [
            {
                "item": "SKU1",
                "week": "2025-01-W1",
                "gross_req": 30,
                "scheduled_receipts": 3,
                "on_hand_start": 12,
                "net_req": 6,
                "planned_order_receipt": 22,
                "planned_order_release": 22,
                "planned_order_receipt_adj": 21,
                "planned_order_release_adj": 21,
                "on_hand_end": 7,
                "lt_weeks": 2,
                "lot": 1,
                "moq": 0,
            }
        ]
    }

    rows = build_plan_series_from_plan_final("v-test", plan_final)
    assert len(rows) == 1
    row = rows[0]
    assert row["inventory_open"] == 12.0
    assert row["inventory_close"] == 7.0


def test_attach_inventory_to_detail_series_injects_values():
    detail = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "sku": "SKU1",
                "week": "2025-01-W1",
                "demand": 10,
                "supply": 10,
                "backlog": 0,
            }
        ]
    }
    plan_final = {
        "rows": [
            {
                "item": "SKU1",
                "week": "2025-01-W1",
                "on_hand_start": 5,
                "on_hand_end": 3,
            }
        ]
    }
    series = build_plan_series("v-test", aggregate=None, detail=detail)
    attach_inventory_to_detail_series(series, plan_final)
    det = next(r for r in series if r["level"] == "det")
    assert det["inventory_open"] == 5.0
    assert det["inventory_close"] == 3.0
    extra = json.loads(det["extra_json"])
    assert extra["on_hand_start"] == 5.0
    assert extra["on_hand_end"] == 3.0
