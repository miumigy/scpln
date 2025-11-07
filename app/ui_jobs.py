from app.api import app
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import db
import json
from app.template_filters import register_format_filters

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
register_format_filters(templates)


@app.get("/ui/jobs", response_class=HTMLResponse)
def ui_jobs(
    request: Request, status: str | None = None, offset: int = 0, limit: int = 20
):
    data = db.list_jobs(status, offset, limit)
    rows = data.get("jobs", [])
    # planningの結果(out_dir)を抽出し、テンプレートで使いやすくする
    import json as _json

    for r in rows:
        try:
            if r.get("type") == "planning" and r.get("result_json"):
                js = _json.loads(r.get("result_json"))
                if isinstance(js, dict) and js.get("out_dir"):
                    r["out_dir"] = js.get("out_dir")
                if isinstance(js, dict) and js.get("version_id"):
                    r["plan_version_id"] = js.get("version_id")
        except Exception:
            pass
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "rows": rows,
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
    # Parse planning result if exists
    result = None
    try:
        if row.get("result_json"):
            result = json.loads(row.get("result_json"))
    except Exception:
        result = None
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {"job": row, "result": result, "subtitle": "Jobs"},
    )
