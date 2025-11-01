from __future__ import annotations

from pathlib import Path

import pytest

from scripts.calendar_utils import (
    build_calendar_lookup,
    get_week_distribution,
    load_planning_calendar,
    map_due_to_week,
    ordered_weeks,
)


def _calendar_path() -> str:
    base = Path(__file__).resolve().parents[1]
    return str(base / "samples" / "planning" / "planning_calendar.json")


def test_week_distribution_uses_calendar_weights() -> None:
    spec = load_planning_calendar(_calendar_path())
    assert spec is not None
    lookup = build_calendar_lookup(spec)
    assert lookup is not None

    dist = get_week_distribution("2025-01", lookup, fallback_weeks=4)
    assert len(dist) == 4
    assert pytest.approx(sum(w.ratio for w in dist)) == 1.0
    assert dist[-1].week_code == "2025-W04"

    fallback = get_week_distribution("2024-12", lookup, fallback_weeks=3)
    assert [w.week_code for w in fallback] == [
        "2024-12-W1",
        "2024-12-W2",
        "2024-12-W3",
    ]


def test_ordered_weeks_and_due_mapping() -> None:
    spec = load_planning_calendar(_calendar_path())
    assert spec is not None
    lookup = build_calendar_lookup(spec)
    assert lookup is not None

    ordered = ordered_weeks(["2025-W06", "2025-W01", "2025-W05"], lookup)
    assert ordered == ["2025-W01", "2025-W05", "2025-W06"]

    assert map_due_to_week("2025-01-05", lookup, fallback_weeks=4) == "2025-W01"
    assert map_due_to_week("2025-01", lookup, fallback_weeks=4) == "2025-W04"
    # 未定義カレンダーの場合はフォールバック
    assert map_due_to_week("2025-03", lookup, fallback_weeks=4) == "2025-03-W4"

    assert ordered_weeks(["2025-W02", "2025-W01"], None) == ["2025-W01", "2025-W02"]
