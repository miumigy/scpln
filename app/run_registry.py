import threading
import os
from typing import Dict, Any, List, Optional


class RunRegistry:
    def __init__(self, capacity: int = 50):
        self.capacity = capacity
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self._lock = threading.Lock()

    def put(self, run_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id].update(payload)
                return
            self._runs[run_id] = payload
            self._order.append(run_id)
            if len(self._order) > self.capacity:
                old = self._order.pop(0)
                self._runs.pop(old, None)

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._runs.get(run_id, {}))

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(self._runs[r]) for r in reversed(self._order)]

    def list_ids(self) -> List[str]:
        with self._lock:
            return list(reversed(self._order))

    def delete(self, run_id: str) -> None:
        with self._lock:
            if run_id in self._runs:
                self._runs.pop(run_id, None)
                try:
                    self._order.remove(run_id)
                except ValueError:
                    pass


def _capacity_from_env(default: int = 50) -> int:
    s = os.getenv("REGISTRY_CAPACITY")
    if not s:
        return default
    try:
        v = int(s)
        return v if v > 0 else default
    except Exception:
        return default


_BACKEND = os.getenv("REGISTRY_BACKEND", "memory").lower()
_DB_MAX_ROWS = int(os.getenv("RUNS_DB_MAX_ROWS", "0") or 0)

if _BACKEND == "db":
    try:
        from .run_registry_db import RunRegistryDB  # type: ignore

        REGISTRY = RunRegistryDB()  # type: ignore
    except Exception:
        # フォールバック: DB初期化失敗時はメモリ実装
        REGISTRY = RunRegistry(capacity=_capacity_from_env(50))
else:
    REGISTRY = RunRegistry(capacity=_capacity_from_env(50))
