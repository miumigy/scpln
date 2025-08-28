from __future__ import annotations

from typing import Dict, List
import threading

_lock = threading.Lock()
_latest_by_scenario: Dict[int, List[str]] = {}


def record(scenario_id: int | None, run_id: str) -> None:
    if scenario_id is None:
        return
    try:
        sid = int(scenario_id)
    except Exception:
        return
    with _lock:
        arr = _latest_by_scenario.setdefault(sid, [])
        # 先頭を最新として保持（重複は前へ）
        if run_id in arr:
            arr.remove(run_id)
        arr.insert(0, run_id)
        # 上限は少数で十分
        if len(arr) > 5:
            del arr[5:]


def latest(scenario_id: int, limit: int = 1) -> List[str]:
    try:
        sid = int(scenario_id)
    except Exception:
        return []
    with _lock:
        arr = _latest_by_scenario.get(sid, [])
        if limit <= 0:
            return []
        return list(arr[:limit])
