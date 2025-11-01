from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Set, Tuple

from pydantic import ValidationError

from core.config.models import PlanningCalendarSpec


@dataclass(frozen=True)
class WeekDistribution:
    """週単位の配分情報。"""

    week_code: str
    ratio: float
    weight: float
    sequence: int


@dataclass
class PlanningCalendarLookup:
    """Planningカレンダーの検索用インデックス。"""

    spec: PlanningCalendarSpec
    distributions: Dict[str, List[WeekDistribution]]
    week_order: List[str]
    week_ranges: List[Tuple[date, date, str]]
    period_last_week: Dict[str, str]
    week_to_period: Dict[str, str]


def load_planning_calendar(path: Optional[str]) -> Optional[PlanningCalendarSpec]:
    """パスを指定してPlanningカレンダーを読み込む。"""

    if not path:
        return None
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)
    try:
        return PlanningCalendarSpec.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"planning_calendarの形式が不正です: {exc}") from exc


def build_calendar_lookup(
    spec: Optional[PlanningCalendarSpec],
) -> Optional[PlanningCalendarLookup]:
    """Planningカレンダー仕様からLookUpを構築する。"""

    if not spec:
        return None

    distributions: Dict[str, List[WeekDistribution]] = {}
    week_order: List[str] = []
    week_ranges: List[Tuple[date, date, str]] = []
    period_last_week: Dict[str, str] = {}
    seen: Set[str] = set()
    week_to_period: Dict[str, str] = {}

    for period in spec.periods:
        weeks = sorted(
            period.weeks,
            key=lambda w: (w.sequence, w.start_date, w.week_code),
        )
        if not weeks:
            continue

        weights = [max(0.0, float(w.weight or 0.0)) for w in weeks]
        total = sum(weights)
        if total <= 0 and weeks:
            ratios = [1.0 / len(weeks)] * len(weeks)
        elif total > 0:
            ratios = [w / total for w in weights]
        else:
            ratios = []

        entries: List[WeekDistribution] = []
        for idx, week in enumerate(weeks):
            ratio = ratios[idx] if idx < len(ratios) else 0.0
            entry = WeekDistribution(
                week_code=week.week_code,
                ratio=ratio,
                weight=weights[idx] if idx < len(weights) else 0.0,
                sequence=week.sequence,
            )
            entries.append(entry)

            if week.week_code not in seen:
                week_order.append(week.week_code)
                seen.add(week.week_code)
            week_ranges.append((week.start_date, week.end_date, week.week_code))
            week_to_period[week.week_code] = period.period
        if entries:
            distributions[period.period] = entries
            period_last_week[period.period] = entries[-1].week_code

    return PlanningCalendarLookup(
        spec=spec,
        distributions=distributions,
        week_order=week_order,
        week_ranges=week_ranges,
        period_last_week=period_last_week,
        week_to_period=week_to_period,
    )


def get_week_distribution(
    period: str,
    lookup: Optional[PlanningCalendarLookup],
    fallback_weeks: int,
) -> List[WeekDistribution]:
    """期間コードに対する週配分リストを取得（フォールバックは等分）。"""

    if lookup and period in lookup.distributions:
        return lookup.distributions[period]

    weeks = max(1, int(fallback_weeks or 1))
    ratio = 1.0 / weeks
    return [
        WeekDistribution(
            week_code=f"{period}-W{i}",
            ratio=ratio,
            weight=0.0,
            sequence=i,
        )
        for i in range(1, weeks + 1)
    ]


def ordered_weeks(
    week_codes: Iterable[str],
    lookup: Optional[PlanningCalendarLookup],
) -> List[str]:
    """週コード集合をPlanningカレンダー順で整列する。"""

    unique: List[str] = []
    seen: Set[str] = set()
    for code in week_codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)

    if not lookup:
        return sorted(unique)

    ordered: List[str] = []
    for code in lookup.week_order:
        if code in seen and code not in ordered:
            ordered.append(code)

    for code in unique:
        if code not in ordered:
            ordered.append(code)

    return ordered


def resolve_period_for_week(
    week_code: str,
    lookup: Optional[PlanningCalendarLookup],
) -> str:
    """週コードから期間コードを推定する。"""

    if not week_code:
        return ""
    if lookup and week_code in lookup.week_to_period:
        return lookup.week_to_period[week_code]
    if len(week_code) >= 7 and week_code[4] == "-":
        # ISO週形式 (YYYY-Www) は週内の木曜日で属する月を返す
        if len(week_code) >= 8 and week_code[5].upper() == "W":
            try:
                year = int(week_code[:4])
                week = int("".join(ch for ch in week_code.split("W", 1)[-1] if ch.isdigit())[:2] or "0")
                iso_ref = date.fromisocalendar(year, week, 4)
                return f"{iso_ref.year:04d}-{iso_ref.month:02d}"
            except Exception:
                pass
        return week_code[:7]
    return week_code


def map_due_to_week(
    due: str,
    lookup: Optional[PlanningCalendarLookup],
    fallback_weeks: int,
) -> Optional[str]:
    """入荷予定日などを週コードへマップする。"""

    if not due:
        return None
    due = str(due)

    if lookup:
        if due in lookup.week_order:
            return due
        try:
            due_date = date.fromisoformat(due)
        except ValueError:
            due_date = None

        if due_date:
            for start, end, code in lookup.week_ranges:
                if start <= due_date <= end:
                    return code

        if len(due) == 7 and due.count("-") == 1:
            if due in lookup.period_last_week:
                return lookup.period_last_week[due]

    if len(due) == 7 and due.count("-") == 1:
        wk = max(1, int(fallback_weeks or 1))
        return f"{due}-W{wk}"

    try:
        y, m, d = due.split("-")
        day = int(d)
    except Exception:
        return None

    wk = 1 if day <= 7 else 2 if day <= 14 else 3 if day <= 21 else 4
    return f"{y}-{m}-W{wk}"


__all__ = [
    "WeekDistribution",
    "PlanningCalendarLookup",
    "load_planning_calendar",
    "build_calendar_lookup",
    "get_week_distribution",
    "ordered_weeks",
    "resolve_period_for_week",
    "map_due_to_week",
]
