from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


JST = timezone(timedelta(hours=9))


def ms_to_jst_str(ms: Any) -> str:
    """ミリ秒Unix時刻をJSTのYYYY/MM/DD hh:mm:ss文字列に整形。

    - 整数/浮動小数/文字列を受け取り、変換不可の場合は空文字を返す。
    """
    if ms is None:
        return ""
    try:
        ts = float(ms) / 1000.0
        dt = datetime.fromtimestamp(ts, tz=JST)
        return dt.strftime("%Y/%m/%d %H:%M:%S")
    except Exception:
        return ""


def _coerce_decimal(value: Any) -> Decimal | None:
    """入力値をDecimal化（NaN/Infinity/空はNone）。"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        target = text
    else:
        target = str(value)
    try:
        dec = Decimal(target)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return dec if dec.is_finite() else None


def format_number(value: Any, decimals: int = 2, strip_trailing: bool = True) -> str:
    """数値を3桁区切り＋最大decimals桁へ整形。"""
    dec = _coerce_decimal(value)
    if dec is None:
        return ""
    decimals = max(0, int(decimals))
    quant = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    rounded = dec.quantize(quant, rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = Decimal(0)
    formatted = format(rounded, f",.{decimals}f")
    if strip_trailing and decimals > 0:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def format_percent(value: Any, decimals: int = 2) -> str:
    """0-1の比率を百分率表記へ変換。"""
    dec = _coerce_decimal(value)
    if dec is None:
        return ""
    scaled = dec * Decimal(100)
    formatted = format_number(scaled, decimals=decimals, strip_trailing=False)
    return f"{formatted}%"


_PERCENT_KEYS = {
    "fill_rate",
    "service_level",
    "on_time_rate",
    "capacity_util",
    "capacity_utilization",
}
_PERCENT_SUFFIXES = ("_rate", "_ratio", "_util", "_utilization")


def _looks_percent_key(key: str | None) -> bool:
    if not key:
        return False
    lowered = key.lower()
    if lowered in _PERCENT_KEYS:
        return True
    return any(lowered.endswith(suffix) for suffix in _PERCENT_SUFFIXES)


def format_metric(value: Any, key: str | None = None) -> str:
    """メトリック名から自動判別して整形。"""
    if key and _looks_percent_key(key):
        return format_percent(value)
    return format_number(value)
