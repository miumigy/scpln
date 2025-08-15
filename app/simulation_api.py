from uuid import uuid4
from fastapi import Query
from app.api import app, validate_input, set_last_summary
from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator

@app.post("/simulation")
def post_simulation(payload: SimulationInput, include_trace: bool = Query(False)):
    validate_input(payload)
    run_id = str(uuid4())
    sim = SupplyChainSimulator(payload)
    results, daily_pl = sim.run()
    summary = sim.compute_summary()
    set_last_summary(summary)
    resp = {
        "run_id": run_id,
        "results": results,
        "daily_profit_loss": daily_pl,
    }
    if include_trace:
        # Issue1/拡張で実装済みの cost_trace を返す
        resp["cost_trace"] = getattr(sim, "cost_trace", [])
    return resp
