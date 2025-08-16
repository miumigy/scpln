from uuid import uuid4
from fastapi import Query
from app.api import app, validate_input, set_last_summary
from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
import time
from app.run_registry import REGISTRY


@app.post("/simulation")
def post_simulation(payload: SimulationInput, include_trace: bool = Query(False)):
    validate_input(payload)
    run_id = str(uuid4())
    start = time.time()
    sim = SupplyChainSimulator(payload)
    results, daily_pl = sim.run()
    duration_ms = int((time.time() - start) * 1000)
    try:
        summary = sim.compute_summary()
    except Exception:
        summary = {}
    REGISTRY.put(
        run_id,
        {
            "run_id": run_id,
            "started_at": int(start * 1000),
            "duration_ms": duration_ms,
            "schema_version": getattr(payload, "schema_version", "1.0"),
            "summary": summary,
            # 後から参照できるよう主要出力も保存
            "results": results,
            "daily_profit_loss": daily_pl,
            "cost_trace": getattr(sim, "cost_trace", []),
        },
    )
    set_last_summary(summary)
    # UIとの互換性のため、profit_loss と summary も返す。
    # また、トレースCSV用途で cost_trace も常に返す（サイズ増を許容）。
    resp = {
        "run_id": run_id,
        "results": results,
        "daily_profit_loss": daily_pl,
        "profit_loss": daily_pl,
        "summary": summary,
        "cost_trace": getattr(sim, "cost_trace", []),
    }
    return resp
