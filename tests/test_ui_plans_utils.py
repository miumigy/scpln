import json

from app.ui_plans import _convert_weekly_summary_from_repo


def test_convert_weekly_summary_from_repo_basic():
    rows = [
        {
            "time_bucket_key": "2025-01-W01",
            "boundary_zone": "pre",
            "supply": 9,
            "demand": 8,
            "backlog": 2,
            "capacity_used": 10,
            "extra_json": json.dumps(
                {
                    "spill_in": 1,
                    "spill_out": 2,
                    "capacity": 10,
                    "carried_slack_in": 0.5,
                    "slack_carry_out": 0.1,
                    "zone": "pre",
                }
            ),
        }
    ]
    converted = _convert_weekly_summary_from_repo(rows)
    assert converted
    item = converted[0]
    assert item["week"] == "2025-01-W01"
    assert item["zone"] == "pre"
    assert item["spill_in"] == 1.0
    assert item["adjusted_load"] == 9.0
