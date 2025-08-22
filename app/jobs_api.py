from typing import Any, Dict
import json
import time
from uuid import uuid4

from fastapi import Body, HTTPException, Query
from app.api import app
from app.jobs import JOB_MANAGER
from app import db


@app.post("/jobs/simulation")
def post_job_simulation(body: Dict[str, Any] = Body(...)):
    job_id = JOB_MANAGER.submit_simulation(body)
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return row


@app.get("/jobs")
def list_jobs(status: str | None = Query(None), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    return db.list_jobs(status, offset, limit)


@app.post("/jobs/{job_id}/retry")
def post_job_retry(job_id: str, body: Dict[str, Any] | None = Body(None)):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row.get("status") not in ("failed", "canceled"):
        raise HTTPException(status_code=409, detail="job is not in failed/canceled state")
    if body and body.get("params") is not None:
        db.update_job_params(job_id, json.dumps(body.get("params")))
    now = int(time.time() * 1000)
    db.update_job_status(job_id, status="queued", submitted_at=now, started_at=None, finished_at=None, run_id=None, error=None)
    JOB_MANAGER.enqueue_existing(job_id)
    return {"status": "queued", "job_id": job_id}


@app.post("/jobs/{job_id}/cancel")
def post_job_cancel(job_id: str):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row.get("status") != "queued":
        raise HTTPException(status_code=409, detail="only queued job can be canceled")
    now = int(time.time() * 1000)
    db.update_job_status(job_id, status="canceled", finished_at=now)
    return {"status": "canceled", "job_id": job_id}
