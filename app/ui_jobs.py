from app.api import app
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import db

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/ui/jobs", response_class=HTMLResponse)
def ui_jobs(
    request: Request, status: str | None = None, offset: int = 0, limit: int = 20
):
    data = db.list_jobs(status, offset, limit)
    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "rows": data.get("jobs", []),
            "total": data.get("total", 0),
            "offset": data.get("offset", 0),
            "limit": data.get("limit", limit),
            "status": status or "",
            "subtitle": "Jobs",
        },
    )


@app.get("/ui/jobs/{job_id}", response_class=HTMLResponse)
def ui_job_detail(request: Request, job_id: str):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return templates.TemplateResponse(
        "job_detail.html",
        {"request": request, "job": row, "subtitle": "Jobs"},
    )
