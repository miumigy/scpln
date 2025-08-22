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

