import os
import json
import time
from typing import Any, Dict

from app import db
from app.run_registry import REGISTRY
from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
from engine.aggregation import aggregate_by_time, rollup_axis
import logging


_BACKEND = os.getenv("JOBS_BACKEND", "memory").lower()

def is_enabled() -> bool:
    return _BACKEND == "rq"


def _rq_queue():
    from rq import Queue
    from redis import Redis
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    conn = Redis.from_url(url)
    qname = os.getenv("RQ_QUEUE", "default")
    return Queue(qname, connection=conn)


def submit_simulation(payload: Dict[str, Any]) -> str:
    job_id = os.urandom(8).hex()
    now = int(time.time() * 1000)
    db.create_job(job_id, "simulation", "queued", now, json.dumps(payload, ensure_ascii=False))
    q = _rq_queue()
    q.enqueue(run_simulation_task, job_id, payload, job_id=job_id)
    return job_id


def run_simulation_task(job_id: str, payload: Dict[str, Any]):
    started = int(time.time() * 1000)
    db.update_job_status(job_id, status="running", started_at=started)
    t0 = time.monotonic()
    try:
        config_id = payload.pop("config_id", None)
        cfg_json = None
        try:
            if config_id is not None:
                cre = db.get_config(int(config_id))
                if cre and cre.get("json_text") is not None:
                    cfg_json = json.loads(cre.get("json_text"))
        except Exception:
            cfg_json = None
        # fallback: store payload for later matching when explicit config not provided
        try:
            if cfg_json is None and payload:
                cfg_json = payload
        except Exception:
            pass
        sim_input = SimulationInput(**payload)
        sim = SupplyChainSimulator(sim_input)
        results, daily_pl = sim.run()
        try:
            summary = sim.compute_summary()
        except Exception:
            summary = {}
        REGISTRY.put(
            job_id,
            {
                "run_id": job_id,
                "started_at": started,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "schema_version": getattr(sim_input, "schema_version", "1.0"),
                "summary": summary,
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
                    "route": "/jobs_rq/simulation",
                    "run_id": job_id,
                    "config_id": config_id,
                    "config_json_present": bool(cfg_json),
                },
            )
        except Exception:
            pass
        db.update_job_status(job_id, status="succeeded", finished_at=int(time.time() * 1000), run_id=job_id)
    except Exception as e:
        db.update_job_status(job_id, status="failed", finished_at=int(time.time() * 1000), error=str(e))


def submit_aggregate(payload: Dict[str, Any]) -> str:
    job_id = os.urandom(8).hex()
    now = int(time.time() * 1000)
    db.create_job(job_id, "aggregate", "queued", now, json.dumps(payload, ensure_ascii=False))
    q = _rq_queue()
    q.enqueue(run_aggregate_task, job_id, payload, job_id=job_id)
    return job_id


def run_aggregate_task(job_id: str, cfg: Dict[str, Any]):
    started = int(time.time() * 1000)
    db.update_job_status(job_id, status="running", started_at=started)
    t0 = time.monotonic()
    try:
        run_id = cfg.get("run_id")
        dataset = (cfg.get("dataset") or "daily_profit_loss").lower()
        bucket = (cfg.get("bucket") or "week").lower()
        group_keys = cfg.get("group_keys") or []
        sum_fields = cfg.get("sum_fields") or None
        product_level = cfg.get("product_level")
        product_map = cfg.get("product_map") or None
        product_key = cfg.get("product_key") or "item"
        location_level = cfg.get("location_level")
        location_map = cfg.get("location_map") or None
        location_key = cfg.get("location_key") or "node"
        week_start_offset = int(cfg.get("week_start_offset") or 0)
        month_len = int(cfg.get("month_len") or 30)

        run = REGISTRY.get(run_id) if run_id else None
        if not run:
            raise RuntimeError("run not found")
        rows = []
        if dataset in ("pl", "daily_profit_loss"):
            rows = run.get("daily_profit_loss") or []
        elif dataset == "trace":
            rows = run.get("cost_trace") or []
        elif dataset == "results":
            rows = run.get("results") or []
        else:
            raise RuntimeError("unknown dataset")
        if not isinstance(rows, list):
            rows = []
        if rows and isinstance(rows[0], dict) and (("day" in rows[0]) or ("date" in rows[0]) or (cfg.get("date_field"))):
            agg_time = aggregate_by_time(
                rows,
                bucket,
                day_field="day",
                sum_fields=sum_fields,
                group_keys=group_keys,
                week_start_offset=week_start_offset,
                month_len=month_len,
                date_field=cfg.get("date_field"),
                tz=cfg.get("tz"),
                calendar_mode=cfg.get("calendar_mode"),
            )
        else:
            agg_time = rows
        keep = ["period"] if agg_time and "period" in agg_time[0] else []
        out_rows = rollup_axis(
            agg_time,
            product_key=product_key,
            product_map=(product_map or db.get_product_hierarchy()),
            product_level=product_level,
            location_key=location_key,
            location_map=(location_map or db.get_location_hierarchy()),
            location_level=location_level,
            keep_fields=keep,
            sum_fields=sum_fields,
        ) if (product_level or location_level) else agg_time
        db.set_job_result(job_id, json.dumps(out_rows, ensure_ascii=False))
        db.update_job_status(job_id, status="succeeded", finished_at=int(time.time() * 1000))
    except Exception as e:
        db.update_job_status(job_id, status="failed", finished_at=int(time.time() * 1000), error=str(e))
