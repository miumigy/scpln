from __future__ import annotations

from app.api import app
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import db


_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/ui/plans", response_class=HTMLResponse)
def ui_plans(request):
    plans = db.list_plan_versions(limit=200)
    # enrich with summary if exists (lightweight; avoid N+1 heavy loads)
    rows = []
    for p in plans:
        ver = p.get("version_id")
        recon = db.get_plan_artifact(ver, "reconciliation_log.json") or {}
        summary = (recon or {}).get("summary") or {}
        rows.append({**p, "recon_summary": summary})
    return templates.TemplateResponse(
        "plans.html",
        {
            "request": request,
            "subtitle": "プランバージョン一覧",
            "plans": rows,
        },
    )

