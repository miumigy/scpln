from app import ui_plans


def test_prepare_delta_rows_natural_sort():
    rows = [
        {"period": "M10", "family": "F1"},
        {"period": "M2", "family": "F2"},
        {"period": "M1", "family": "F3"},
    ]

    sorted_rows = ui_plans._prepare_delta_rows(rows, limit=None)

    assert [r["period"] for r in sorted_rows] == ["M1", "M2", "M10"]
