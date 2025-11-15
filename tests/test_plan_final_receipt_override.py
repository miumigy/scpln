from app import plans_api


def test_apply_plan_final_receipts_overrides_supply():
    detail = {
        "rows": [
            {
                "family": "F1",
                "period": "P1",
                "sku": "SKU-A",
                "week": "P1-W1",
                "demand": 10,
                "supply": 0,
                "supply_plan": 0,
                "backlog": 10,
            }
        ]
    }
    aggregate = {
        "rows": [
            {
                "family": "F1",
                "period": "P1",
                "demand": 10,
                "supply": 0,
                "backlog": 10,
            }
        ]
    }
    plan_final = {
        "rows": [
            {"sku": "SKU-A", "week": "P1-W1", "planned_order_receipt_adj": 6},
            {"sku": "SKU-A", "week": "P1-W2", "planned_order_receipt_adj": 4},
        ]
    }

    updated_detail, updated_agg = plans_api._apply_plan_final_receipts(
        detail, aggregate, plan_final
    )

    row = updated_detail["rows"][0]
    assert row["supply"] == 6
    assert row["supply_plan"] == 6
    assert row["backlog"] == 4

    agg_row = updated_agg["rows"][0]
    assert agg_row["supply"] == 6
    assert agg_row["backlog"] == 4


def test_apply_plan_final_receipts_sets_zero_when_receipt_missing_in_week():
    detail = {
        "rows": [
            {
                "family": "F1",
                "period": "P1",
                "sku": "SKU-A",
                "week": "P1-W1",
                "demand": 10,
                "supply": 10,
                "supply_plan": 10,
                "backlog": 0,
            },
            {
                "family": "F1",
                "period": "P1",
                "sku": "SKU-A",
                "week": "P1-W2",
                "demand": 0,
                "supply": 0,
                "supply_plan": 0,
                "backlog": 0,
            },
        ]
    }
    aggregate = {
        "rows": [
            {"family": "F1", "period": "P1", "demand": 10, "supply": 10, "backlog": 0}
        ]
    }
    plan_final = {
        "rows": [
            {"sku": "SKU-A", "week": "P1-W2", "planned_order_receipt_adj": 10},
        ]
    }

    updated_detail, _ = plans_api._apply_plan_final_receipts(
        detail, aggregate, plan_final
    )

    w1 = updated_detail["rows"][0]
    w2 = updated_detail["rows"][1]
    assert w1["supply"] == 0  # receipt exists for SKU so weeks without receipt become 0
    assert w1["backlog"] == 10
    assert w2["supply"] == 10
