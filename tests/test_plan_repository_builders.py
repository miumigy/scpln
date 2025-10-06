from core.plan_repository_builders import (
    build_plan_kpis_from_aggregate,
    build_plan_series,
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
