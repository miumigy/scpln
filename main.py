from app.api import app
from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
import logging
import math
from collections import defaultdict
from typing import Optional
import time as _time
from app.run_registry import REGISTRY as _REGISTRY
from app import db as _db

try:
    from app import metrics as _metrics  # noqa: F401  # /metrics を副作用で登録
except Exception:
    pass

try:
    from app import simulation_api as _simulation_api  # noqa: F401

    _SIM_LOADED = True
except Exception:
    _SIM_LOADED = False

try:
    from app import run_compare_api as _run_compare_api  # noqa: F401
except Exception:
    pass

try:
    from app import run_list_api as _run_list_api  # noqa: F401
except Exception:
    pass

try:
    from app import trace_export_api as _trace_export_api  # noqa: F401
except Exception:
    pass

try:
    from app import ui_runs as _ui_runs  # noqa: F401
except Exception:
    pass

try:
    from app import ui_compare as _ui_compare  # noqa: F401
except Exception:
    pass

# jobs API/UI の登録
try:
    from app import jobs_api as _jobs_api  # noqa: F401
    from app import ui_jobs as _ui_jobs  # noqa: F401
except Exception:
    pass

try:
    from app import config_api as _config_api  # noqa: F401
    from app import ui_configs as _ui_configs  # noqa: F401
except Exception:
    pass

# hierarchy API/UI の登録（商品/場所の階層マスタ）
try:
    from app import hierarchy_api as _hierarchy_api  # noqa: F401
    from app import ui_hierarchy as _ui_hierarchy  # noqa: F401
except Exception:
    pass

# phase2: scenarios API/UI
try:
    from app import scenario_api as _scenario_api  # noqa: F401
    from app import ui_scenarios as _ui_scenarios  # noqa: F401
except Exception:
    pass

__all__ = ["app", "SimulationInput", "SupplyChainSimulator"]

# Fallback: define /simulation route here when import failed (to avoid 404)
if not globals().get("_SIM_LOADED", False):
    from fastapi import Query, Request
    import json as _json

    @app.post("/simulation")
    def _fallback_post_simulation(
        payload: SimulationInput,
        include_trace: bool = Query(False),
        config_id: Optional[int] = Query(None),
        request: Request = None,
    ):
        rid = str(__import__("uuid").uuid4())
        start = _time.time()
        sim = SupplyChainSimulator(payload)
        results, daily_pl = sim.run()
        try:
            summary = sim.compute_summary()
        except Exception:
            summary = {}
        cfg_json = None
        # header fallback
        try:
            if config_id is None and request is not None:
                hdr = request.headers.get("X-Config-Id")
                if hdr:
                    config_id = int(hdr)
        except Exception:
            pass
        try:
            if config_id is not None:
                rec = _db.get_config(int(config_id))
                if rec and rec.get("json_text") is not None:
                    cfg_json = _json.loads(rec.get("json_text"))
        except Exception:
            cfg_json = None
        try:
            if cfg_json is None and payload is not None:
                cfg_json = payload.model_dump()
        except Exception:
            pass
        _REGISTRY.put(
            rid,
            {
                "run_id": rid,
                "started_at": int(start * 1000),
                "duration_ms": int((_time.time() - start) * 1000),
                "schema_version": getattr(payload, "schema_version", "1.0"),
                "summary": summary,
                "results": results,
                "daily_profit_loss": daily_pl,
                "cost_trace": getattr(sim, "cost_trace", []),
                "config_id": config_id,
                "config_json": cfg_json,
            },
        )
        return {
            "run_id": rid,
            "results": results,
            "daily_profit_loss": daily_pl,
            "profit_loss": daily_pl,
            "summary": summary,
            "cost_trace": getattr(sim, "cost_trace", []),
        }


if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.DEBUG,
        filename="simulation.log",
        filemode="w",
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    print("--- Script started ---")

    with open("static/default_input.json", encoding="utf-8") as f:
        sim_input_dict = json.load(f)
    sim_input = SimulationInput(**sim_input_dict)

    simulator = SupplyChainSimulator(sim_input)
    results, profit_loss = simulator.run()

    logging.info("--- SIMULATION TEST COMPLETE ---")
    logging.info("--- PROFIT/LOSS DATA ---")
    for day_pl in profit_loss:
        logging.info(day_pl)

    # 期末未着は pending_shipments（シミュ後日付）から集計
    in_transit_at_end = defaultdict(float)
    for arrival_day, orders in simulator.pending_shipments.items():
        for rec in orders:
            if len(rec) == 4:
                item, qty, _src, dest = rec
            else:
                item, qty, _src, dest, _is_bo = rec
            in_transit_at_end[(dest, item)] += qty

    logging.info("CUMULATIVE ORDERED:")
    logging.info(simulator.cumulative_ordered)
    logging.info("CUMULATIVE RECEIVED:")
    logging.info(simulator.cumulative_received)
    logging.info("IN TRANSIT AT END:")
    logging.info(in_transit_at_end)

    validation_passed = True
    all_keys = set(simulator.cumulative_ordered.keys()) | set(
        simulator.cumulative_received.keys()
    )

    for key in all_keys:
        ordered = simulator.cumulative_ordered.get(key, 0)
        received = simulator.cumulative_received.get(key, 0)
        in_transit = in_transit_at_end.get(key, 0)

        if not math.isclose(ordered, received + in_transit, rel_tol=1e-9, abs_tol=1e-9):
            validation_passed = False
            logging.error(
                f"VALIDATION FAILED for {key}: Ordered={ordered}, Received={received}, InTransit={in_transit}"
            )

    if validation_passed:
        logging.info(
            "*** VALIDATION SUCCESS: Cumulative Ordered == Cumulative Received + In-Transit at End ***"
        )
    else:
        logging.info("*** VALIDATION FAILURE ***")
