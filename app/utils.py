from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


JST = timezone(timedelta(hours=9))


def _coerce_datetime(value: Any) -> datetime | None:
    """任意入力をJSTタイムゾーンのdatetimeに変換。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        ts = float(value)
        if abs(ts) >= 1e12:  # treat as milliseconds
            ts /= 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # 数値文字列なら数値扱い
        try:
            ts = float(text)
        except ValueError:
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                return None
        else:
            if abs(ts) >= 1e12:
                ts /= 1000.0
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST)


def ms_to_jst_str(ms: Any) -> str:
    """ミリ秒Unix時刻をJSTのYYYY/MM/DD hh:mm:ss文字列に整形。

    - 整数/浮動小数/文字列を受け取り、変換不可の場合は空文字を返す。
    """
    dt = _coerce_datetime(ms)
    return dt.strftime("%Y/%m/%d %H:%M:%S") if dt else ""


def format_datetime(value: Any) -> str:
    """入力値をJST日時文字列へ変換（ms/秒/ISO8601/datetimeに対応）。"""
    dt = _coerce_datetime(value)
    return dt.strftime("%Y/%m/%d %H:%M:%S") if dt else ""


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


def to_json(value: Any, *, indent: int = 2) -> str:
    """Dump a value as pretty JSON for templates."""
    try:
        return json.dumps(value, ensure_ascii=False, indent=indent, default=str)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)
