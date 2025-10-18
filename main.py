# ... 既存のインポート ...

from app.api import app
import os
from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
import logging
import math
from collections import defaultdict
from typing import Optional
import time as _time
from app.run_registry import REGISTRY as _REGISTRY
from prometheus_client import make_asgi_app


metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


try:
    from app import metrics as _metrics  # noqa: F401  # /metrics を副作用で登録
except Exception:
    pass

__all__ = ["app", "SimulationInput", "SupplyChainSimulator"]

from fastapi.responses import RedirectResponse

from fastapi import Query, Request
from fastapi.responses import RedirectResponse
from fastapi.exceptions import HTTPException
from starlette.responses import JSONResponse

@app.exception_handler(Exception)
async def unicorn_exception_handler(request: Request, exc: Exception):
    logging.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "message": f"Internal Server Error: {exc}",
            "detail": "An unexpected error occurred. Please check server logs.",
        },
    )

@app.get("/")
def read_root():
    return RedirectResponse(url="/ui/plans")

try:
    from app.metrics import start_metrics_server

    @app.on_event("startup")
    def on_startup():
        if os.getenv("METRICS_ENABLED", "0") == "1":
            start_metrics_server()

except ImportError:
    # app.metrics が存在しない場合などは何もしない
    pass


# Fallback: define /simulation route here when import failed (to avoid 404)
if not globals().get("_SIM_LOADED", False):
    from fastapi import Query, Request

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
            if payload is not None:
                cfg_json = payload.model_dump()
        except Exception:
            cfg_json = None
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


@app.get("/debug-routes")
async def debug_routes():
    routes_info = []
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            routes_info.append({"path": route.path, "methods": list(route.methods)})
    return {"registered_routes": routes_info}

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
