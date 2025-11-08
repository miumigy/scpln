import threading
import os
import time
import logging
from uuid import uuid4
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


def record_canonical_run(
    canonical_config,
    *,
    config_version_id: Optional[int],
    scenario_id: Optional[int],
    plan_version_id: Optional[str] = None,
    plan_job_id: Optional[str] = None,
    input_set_label: Optional[str] = None,
    registry: Optional[RunRegistry] = None,
) -> Optional[str]:
    """Canonical設定を用いたPSIランを実行し、RunRegistryに保存する。

    canonical_config が None または実行失敗時は None を返す。
    """

    if canonical_config is None:
        return None
    if os.getenv("SCPLN_SKIP_SIMULATION_API", "0") == "1":
        return None
    reg = registry or REGISTRY
    try:
        from core.config import build_simulation_input
        from engine.simulator import SupplyChainSimulator

        start = time.time()
        sim_input = build_simulation_input(canonical_config)
        simulator = SupplyChainSimulator(sim_input)
        results, daily_pl = simulator.run()
        duration_ms = int((time.time() - start) * 1000)
        try:
            summary = simulator.compute_summary()
        except Exception:
            summary = {}
        cost_trace = getattr(simulator, "cost_trace", [])
        summary = dict(summary or {})
        if plan_version_id:
            summary.setdefault("_plan_version_id", plan_version_id)
        if input_set_label:
            summary.setdefault("_input_set_label", input_set_label)
        run_id = uuid4().hex
        payload = {
            "run_id": run_id,
            "started_at": int(start * 1000),
            "duration_ms": duration_ms,
            "schema_version": getattr(sim_input, "schema_version", "1.0"),
            "summary": summary,
            "results": results,
            "daily_profit_loss": daily_pl,
            "cost_trace": cost_trace,
            "config_version_id": config_version_id,
            "scenario_id": scenario_id,
            "plan_version_id": plan_version_id,
            "plan_job_id": plan_job_id,
        }
        if input_set_label:
            payload["input_set_label"] = input_set_label
        reg.put(run_id, payload)
        return run_id
    except Exception:
        logging.exception(
            "run_registry_record_failed",
            extra={
                "event": "run_registry_record_failed",
                "config_version_id": config_version_id,
                "scenario_id": scenario_id,
                "plan_version_id": plan_version_id,
            },
        )
        return None
