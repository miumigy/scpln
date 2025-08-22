import threading
import queue
import time
import json
from uuid import uuid4
from typing import Any, Dict, Optional
import os

from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
from app.run_registry import REGISTRY
from app import db
from prometheus_client import Counter as _Counter, Histogram as _Histogram


JOBS_ENABLED = os.getenv("JOBS_ENABLED", "1") == "1"
JOBS_WORKERS = int(os.getenv("JOBS_WORKERS", "1") or 1)

JOBS_ENQUEUED = _Counter("jobs_enqueued_total", "Total jobs enqueued", labelnames=("type",))
JOBS_COMPLETED = _Counter("jobs_completed_total", "Total jobs completed", labelnames=("type",))
JOBS_FAILED = _Counter("jobs_failed_total", "Total jobs failed", labelnames=("type",))
JOBS_DURATION = _Histogram(
    "jobs_duration_seconds",
    "Job execution duration in seconds",
    labelnames=("type",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, float("inf")),
)


class JobManager:
    def __init__(self, workers: int = 1):
        self.workers = max(1, workers)
        self.q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def start(self):
        if self._threads:
            return
        for i in range(self.workers):
            t = threading.Thread(target=self._run_loop, name=f"job-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 2.0):
        self._stop.set()
        try:
            while not self.q.empty():
                try:
                    self.q.get_nowait()
                except Exception:
                    break
        except Exception:
            pass
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()

    def submit_simulation(self, payload: Dict[str, Any]) -> str:
        if not self._threads:
            self.start()
        job_id = uuid4().hex
        now = int(time.time() * 1000)
        db.create_job(job_id, "simulation", "queued", now, json.dumps(payload, ensure_ascii=False))
        self.q.put({"job_id": job_id, "type": "simulation"})
        try:
            JOBS_ENQUEUED.labels(type="simulation").inc()
        except Exception:
            pass
        return job_id

    def _run_loop(self):
        while not self._stop.is_set():
            try:
                job = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            job_id = job.get("job_id")
            jtype = job.get("type")
            # Skip if job is not in queued state anymore (e.g., canceled)
            row = db.get_job(job_id)
            if not row or row.get("status") != "queued":
                continue
            if jtype == "simulation":
                self._run_simulation(job_id)
            else:
                # unknown type: mark failed
                db.update_job_status(job_id, status="failed", finished_at=int(time.time() * 1000), error="unknown job type")
                try:
                    JOBS_FAILED.labels(type=jtype or "unknown").inc()
                except Exception:
                    pass

    def _run_simulation(self, job_id: str):
        started = int(time.time() * 1000)
        db.update_job_status(job_id, status="running", started_at=started)
        t0 = time.monotonic()
        try:
            rec = db.get_job(job_id)
            payload = json.loads(rec.get("params_json") or "{}") if rec else {}
            # parse model
            sim_input = SimulationInput(**payload)
            sim = SupplyChainSimulator(sim_input)
            results, daily_pl = sim.run()
            try:
                summary = sim.compute_summary()
            except Exception:
                summary = {}
            run_id = uuid4().hex
            # store to registry (same as /simulation)
            REGISTRY.put(
                run_id,
                {
                    "run_id": run_id,
                    "started_at": started,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "schema_version": getattr(sim_input, "schema_version", "1.0"),
                    "summary": summary,
                    "results": results,
                    "daily_profit_loss": daily_pl,
                    "cost_trace": getattr(sim, "cost_trace", []),
                },
            )
            finished = int(time.time() * 1000)
            db.update_job_status(job_id, status="succeeded", finished_at=finished, run_id=run_id)
            try:
                JOBS_COMPLETED.labels(type="simulation").inc()
                JOBS_DURATION.labels(type="simulation").observe(time.monotonic() - t0)
            except Exception:
                pass
        except Exception as e:
            finished = int(time.time() * 1000)
            db.update_job_status(job_id, status="failed", finished_at=finished, error=str(e))
            try:
                JOBS_FAILED.labels(type="simulation").inc()
            except Exception:
                pass

    def enqueue_existing(self, job_id: str) -> None:
        row = db.get_job(job_id)
        if not row:
            return
        self.q.put({"job_id": job_id, "type": row.get("type") or "simulation"})


# singleton manager (workers will be started on app startup)
JOB_MANAGER = JobManager(workers=JOBS_WORKERS)
