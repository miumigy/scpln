from typing import Any, Dict
import json
import time

from fastapi import Body, HTTPException, Query, Request
from app.api import app
from app.jobs import JOB_MANAGER

try:
    from app import jobs_rq
except Exception:
    jobs_rq = None  # type: ignore
from app import db
import csv
import io


@app.post("/jobs/simulation")
def post_job_simulation(request: Request, body: Dict[str, Any] = Body(...)):
    import os
    if os.getenv("RBAC_ENABLED", "0") == "1":
        role = request.headers.get("X-Role") if request else None
        org = request.headers.get("X-Org-ID") if request else None
        tenant = request.headers.get("X-Tenant-ID") if request else None
        allowed = {
            x.strip()
            for x in (os.getenv("RBAC_MUTATE_ROLES", "planner,admin").split(","))
            if x.strip()
        }
        if not role or role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden: role not allowed")
        if not org or not tenant:
            raise HTTPException(status_code=400, detail="missing org/tenant headers")
    if jobs_rq and getattr(jobs_rq, "is_enabled", lambda: False)():
        job_id = jobs_rq.submit_simulation(body)
    else:
        job_id = JOB_MANAGER.submit_simulation(body)
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return row


@app.get("/jobs")
def list_jobs(
    status: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return db.list_jobs(status, offset, limit)


@app.post("/jobs/{job_id}/retry")
def post_job_retry(request: Request, job_id: str, body: Dict[str, Any] | None = Body(None)):
    import os
    if os.getenv("RBAC_ENABLED", "0") == "1":
        role = request.headers.get("X-Role") if request else None
        org = request.headers.get("X-Org-ID") if request else None
        tenant = request.headers.get("X-Tenant-ID") if request else None
        allowed = {
            x.strip()
            for x in (os.getenv("RBAC_MUTATE_ROLES", "planner,admin").split(","))
            if x.strip()
        }
        if not role or role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden: role not allowed")
        if not org or not tenant:
            raise HTTPException(status_code=400, detail="missing org/tenant headers")
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row.get("status") not in ("failed", "canceled"):
        raise HTTPException(
            status_code=409, detail="job is not in failed/canceled state"
        )
    if body and body.get("params") is not None:
        db.update_job_params(job_id, json.dumps(body.get("params")))
    now = int(time.time() * 1000)
    db.update_job_status(
        job_id,
        status="queued",
        submitted_at=now,
        started_at=None,
        finished_at=None,
        run_id=None,
        error=None,
    )
    JOB_MANAGER.enqueue_existing(job_id)
    return {"status": "queued", "job_id": job_id}


@app.post("/jobs/{job_id}/cancel")
def post_job_cancel(request: Request, job_id: str):
    import os
    if os.getenv("RBAC_ENABLED", "0") == "1":
        role = request.headers.get("X-Role") if request else None
        org = request.headers.get("X-Org-ID") if request else None
        tenant = request.headers.get("X-Tenant-ID") if request else None
        allowed = {
            x.strip()
            for x in (os.getenv("RBAC_MUTATE_ROLES", "planner,admin").split(","))
            if x.strip()
        }
        if not role or role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden: role not allowed")
        if not org or not tenant:
            raise HTTPException(status_code=400, detail="missing org/tenant headers")
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row.get("status") != "queued":
        raise HTTPException(status_code=409, detail="only queued job can be canceled")
    now = int(time.time() * 1000)
    db.update_job_status(job_id, status="canceled", finished_at=now)
    return {"status": "canceled", "job_id": job_id}


@app.post("/jobs/aggregate")
def post_job_aggregate(request: Request, body: Dict[str, Any] = Body(...)):
    import os
    if os.getenv("RBAC_ENABLED", "0") == "1":
        role = request.headers.get("X-Role") if request else None
        org = request.headers.get("X-Org-ID") if request else None
        tenant = request.headers.get("X-Tenant-ID") if request else None
        allowed = {
            x.strip()
            for x in (os.getenv("RBAC_MUTATE_ROLES", "planner,admin").split(","))
            if x.strip()
        }
        if not role or role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden: role not allowed")
        if not org or not tenant:
            raise HTTPException(status_code=400, detail="missing org/tenant headers")
    # body: {run_id, dataset, bucket, ...}
    if jobs_rq and getattr(jobs_rq, "is_enabled", lambda: False)():
        job_id = jobs_rq.submit_aggregate(body or {})
    else:
        job_id = JOB_MANAGER.submit_aggregate(body or {})
    return {"job_id": job_id}


@app.get("/jobs/{job_id}/result.json")
def get_job_result_json(job_id: str):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="job not succeeded")
    try:
        data = row.get("result_json") or "[]"
        return {"rows": json.loads(data)}
    except Exception:
        return {"rows": []}


@app.get("/jobs/{job_id}/result.csv")
def get_job_result_csv(job_id: str):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="job not succeeded")
    try:
        rows = json.loads(row.get("result_json") or "[]")
    except Exception:
        rows = []
    if not rows:
        rows = []
    # collect headers
    fields = set()
    for r in rows:
        if isinstance(r, dict):
            fields.update(r.keys())
    fieldnames = sorted(fields)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    from fastapi import Response

    headers = {"Content-Disposition": f"attachment; filename=aggregate_{job_id}.csv"}
    return Response(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers
    )
