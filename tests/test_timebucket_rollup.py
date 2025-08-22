from engine.aggregation import aggregate_by_time, rollup_axis


def test_aggregate_by_time_week_basic():
    records = [
        {"day": 1, "node": "S1", "item": "SKU1", "qty": 1.0},
        {"day": 2, "node": "S1", "item": "SKU1", "qty": 2.0},
        {"day": 8, "node": "S1", "item": "SKU1", "qty": 3.0},
    ]
    out = aggregate_by_time(records, "week", day_field="day", sum_fields=["qty"], group_keys=["node", "item"])
    assert out == [
        {"period": 1, "node": "S1", "item": "SKU1", "qty": 3.0},
        {"period": 2, "node": "S1", "item": "SKU1", "qty": 3.0},
    ]


def test_rollup_axis_product_location():
    # period 列（例: 週）を維持しつつ、商品=category、場所=regionへロールアップ
    records = [
        {"period": 1, "node": "S1", "item": "SKU1", "qty": 1.0, "revenue": 10.0},
        {"period": 1, "node": "S2", "item": "SKU2", "qty": 2.0, "revenue": 20.0},
        {"period": 2, "node": "S1", "item": "SKU1", "qty": 3.0, "revenue": 30.0},
    ]
    pmap = {"SKU1": {"item": "I1", "category": "C1"}, "SKU2": {"item": "I2", "category": "C2"}}
    lmap = {"S1": {"region": "R1"}, "S2": {"region": "R2"}}
    out = rollup_axis(
        records,
        product_map=pmap,
        product_level="category",
        location_map=lmap,
        location_level="region",
        keep_fields=["period"],
        sum_fields=["qty", "revenue"],
    )
    # 週×(category,region) で合算
    assert {tuple(x.values()) for x in out} == {
        ("C1", "R1", 1, 1.0, 10.0),
        ("C2", "R2", 1, 2.0, 20.0),
        ("C1", "R1", 2, 3.0, 30.0),
    }

