from __future__ import annotations

from typing import Dict, List, Sequence, Tuple, Any, Optional
from collections import defaultdict
from datetime import datetime, date
try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


TimeBucket = str  # 'day' | 'week' | 'month'


def _period_of_day(day: int, bucket: TimeBucket, *, week_start_offset: int = 0, month_len: int = 30) -> int:
    if bucket == "day":
        return int(day)
    if bucket == "week":
        # 1-based weeks, 7days per week, offset(0..6) to shift week start
        d = int(day) - 1 + int(week_start_offset or 0)
        return d // 7 + 1
    if bucket == "month":
        # 1-based months, configurable length（簡易）
        L = int(month_len or 30)
        return (int(day) - 1) // max(1, L) + 1
    raise ValueError(f"unknown bucket: {bucket}")


def aggregate_by_time(
    records: Sequence[Dict[str, Any]],
    bucket: TimeBucket,
    day_field: str = "day",
    *,
    sum_fields: Optional[Sequence[str]] = None,
    group_keys: Optional[Sequence[str]] = None,
    # calendar strict options (date-based)
    date_field: Optional[str] = None,
    tz: Optional[str] = None,
    calendar_mode: Optional[str] = None,  # 'iso_week'|'month'
    # relaxed options (day-based)
    week_start_offset: int = 0,
    month_len: int = 30,
) -> List[Dict[str, Any]]:
    """日次レコード（dayフィールドを持つ）を time bucket で集計する。
    - sum_fields が None の場合は数値型のフィールドを自動検出して合計
    - group_keys でキー（node/itemなど）単位に分割集計
    返却: {period, <group_keys...>, <sums...>} の配列
    """
    if not records:
        return []
    # 決定するサマリ対象
    if sum_fields is None:
        # 最初のレコードから数値フィールドを検出（day と group_keys を除外）
        sample = records[0]
        deny = set([day_field]) | set(group_keys or [])
        sum_fields = [k for k, v in sample.items() if k not in deny and isinstance(v, (int, float))]
    gkeys = list(group_keys or [])

    agg: Dict[Tuple[Any, ...], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    def compute_period(r: Dict[str, Any]) -> Any:
        if date_field and r.get(date_field) is not None:
            raw = r.get(date_field)
            # accept 'YYYY-MM-DD' or ISO datetime
            try:
                if isinstance(raw, (int, float)):
                    # epoch seconds -> date
                    dt = datetime.utcfromtimestamp(float(raw))
                else:
                    s = str(raw)
                    # split timezone if present; ZoneInfo is optional
                    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                return None
            if tz and ZoneInfo is not None and dt.tzinfo is None:
                try:
                    dt = dt.replace(tzinfo=ZoneInfo(tz))
                except Exception:
                    pass
            d = dt.date()
            if bucket == "day":
                return d.isoformat()
            if bucket == "week" and (calendar_mode in ("iso", "iso_week")):
                iso = d.isocalendar()
                return f"{iso.year}-W{iso.week:02d}"
            if bucket == "month":
                return f"{d.year}-{d.month:02d}"
            # fallback to relaxed day-based period from day field if present
        # relaxed path (day-based)
        return _period_of_day(int(r.get(day_field, 0) or 0), bucket, week_start_offset=week_start_offset, month_len=month_len)

    for r in records:
        period = compute_period(r)
        if period is None:
            # skip malformed rows
            continue
        key_tuple = tuple([period] + [r.get(k) for k in gkeys])
        for f in sum_fields:
            v = r.get(f)
            if isinstance(v, (int, float)):
                agg[key_tuple][f] += float(v)
    out: List[Dict[str, Any]] = []
    for key, sums in sorted(agg.items(), key=lambda kv: kv[0]):
        period = key[0]
        row = {"period": period}
        for i, k in enumerate(gkeys, start=1):
            row[k] = key[i]
        row.update({f: round(v, 6) for f, v in sums.items()})
        out.append(row)
    return out


def rollup_axis(
    records: Sequence[Dict[str, Any]],
    *,
    product_key: str = "item",
    product_map: Optional[Dict[str, Dict[str, str]]] = None,
    product_level: Optional[str] = None,
    location_key: str = "node",
    location_map: Optional[Dict[str, Dict[str, str]]] = None,
    location_level: Optional[str] = None,
    sum_fields: Optional[Sequence[str]] = None,
    keep_fields: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """商品・場所の多段階ロールアップを行う汎用集約。
    - product_map: 例 {"SKU1": {"item":"I1","category":"C1","department":"D1"}, ...}
    - product_level: 例 "category"（None なら元キーを保持）
    - location_map: 例 {"StoreA": {"region":"R1","country":"JP"}, ...}
    - location_level: 例 "region"
    - keep_fields: そのまま出力へ残す（例: period）
    返却: {<product_key or level>, <location_key or level>, <keep_fields...>, <sum_fields...>} の配列
    """
    if not records:
        return []
    sample = records[0]
    if sum_fields is None:
        deny = set([product_key, location_key]) | set(keep_fields or [])
        sum_fields = [k for k, v in sample.items() if k not in deny and isinstance(v, (int, float))]

    def proj_product(val: Any) -> Any:
        if product_map and product_level and isinstance(val, str):
            return (product_map.get(val) or {}).get(product_level, val)
        return val

    def proj_location(val: Any) -> Any:
        if location_map and location_level and isinstance(val, str):
            return (location_map.get(val) or {}).get(location_level, val)
        return val

    agg: Dict[Tuple[Any, ...], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    keep = list(keep_fields or [])
    for r in records:
        p = proj_product(r.get(product_key))
        l = proj_location(r.get(location_key))
        key_tuple = tuple([p, l] + [r.get(k) for k in keep])
        for f in sum_fields:
            v = r.get(f)
            if isinstance(v, (int, float)):
                agg[key_tuple][f] += float(v)
    out: List[Dict[str, Any]] = []
    for key, sums in sorted(agg.items(), key=lambda kv: kv[0]):
        idx = 0
        row = {product_key if not product_level else product_level: key[idx]}; idx += 1
        row.update({location_key if not location_level else location_level: key[idx]}); idx += 1
        for k in keep:
            row[k] = key[idx]; idx += 1
        row.update({f: round(v, 6) for f, v in sums.items()})
        out.append(row)
    return out
