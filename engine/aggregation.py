from __future__ import annotations

from typing import Dict, List, Sequence, Tuple, Any, Optional
from collections import defaultdict


TimeBucket = str  # 'day' | 'week' | 'month'


def _period_of_day(day: int, bucket: TimeBucket) -> int:
    if bucket == "day":
        return int(day)
    if bucket == "week":
        # 1-based weeks, 7days per week
        return (int(day) - 1) // 7 + 1
    if bucket == "month":
        # 1-based months, 30days per month（簡易）
        return (int(day) - 1) // 30 + 1
    raise ValueError(f"unknown bucket: {bucket}")


def aggregate_by_time(
    records: Sequence[Dict[str, Any]],
    bucket: TimeBucket,
    day_field: str = "day",
    sum_fields: Optional[Sequence[str]] = None,
    group_keys: Optional[Sequence[str]] = None,
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
    for r in records:
        period = _period_of_day(int(r.get(day_field, 0) or 0), bucket)
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

