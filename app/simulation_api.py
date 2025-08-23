from uuid import uuid4
import logging
from fastapi import Query, Request
import json
from app import db
from app.api import app, validate_input, set_last_summary
from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
import time
from app.run_registry import REGISTRY
from app.metrics import RUNS_TOTAL, SIM_DURATION
from app.run_registry import _BACKEND, _DB_MAX_ROWS  # type: ignore


@app.post("/simulation")
def post_simulation(
    payload: SimulationInput,
    include_trace: bool = Query(False),
    config_id: int | None = Query(None),
    request: Request = None,
):
    validate_input(payload)
    run_id = str(uuid4())
    start = time.time()
    logging.info("run_started", extra={"event": "run_started", "run_id": run_id})
    sim = SupplyChainSimulator(payload)
    results, daily_pl = sim.run()
    duration_ms = int((time.time() - start) * 1000)
    try:
        SIM_DURATION.observe(duration_ms)
        RUNS_TOTAL.inc()
    except Exception:
        pass
    try:
        summary = sim.compute_summary()
    except Exception:
        summary = {}
    # optional: attach config context (id and json) when provided
    # fallback: header X-Config-Id
    try:
        if config_id is None and request is not None:
            hdr = request.headers.get("X-Config-Id")
            if hdr:
                config_id = int(hdr)
    except Exception:
        pass
    # Attach config context: prefer explicit config_id's JSON; otherwise store payload as config_json for later backfill
    cfg_json = None
    try:
        if config_id is not None:
            rec = db.get_config(int(config_id))
            if rec and rec.get("json_text") is not None:
                cfg_json = json.loads(rec.get("json_text"))
    except Exception:
        cfg_json = None
    # fallback: store input payload for later matching if explicit config is not provided
    try:
        if cfg_json is None and payload is not None:
            cfg_json = payload.model_dump()
    except Exception:
        pass

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
            "config_id": config_id,
            "config_json": cfg_json,
        },
    )
    try:
        logging.debug(
            "config_saved",
            extra={
                "event": "config_saved",
                "route": "/simulation",
                "run_id": run_id,
                "config_id": config_id,
                "config_json_present": bool(cfg_json),
            },
        )
    except Exception:
        pass
    # DB使用時は容量上限で古いRunをクリーンアップ
    try:
        if (
            _BACKEND == "db"
            and _DB_MAX_ROWS > 0
            and hasattr(REGISTRY, "cleanup_by_capacity")
        ):
            REGISTRY.cleanup_by_capacity(_DB_MAX_ROWS)
    except Exception:
        pass
    set_last_summary(summary)
    logging.info(
        "run_completed",
        extra={
            "event": "run_completed",
            "run_id": run_id,
            "duration": duration_ms,
            "results": len(results or []),
            "pl_days": len(daily_pl or []),
            "trace_events": len(getattr(sim, "cost_trace", []) or []),
            "schema": getattr(payload, "schema_version", "1.0"),
        },
    )
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
