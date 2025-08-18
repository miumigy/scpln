from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
