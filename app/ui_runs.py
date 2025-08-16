from app.api import app
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.run_registry import REGISTRY

templates = Jinja2Templates(directory="templates")


@app.get("/ui/runs", response_class=HTMLResponse)
def ui_runs(request: Request):
    runs = REGISTRY.list_ids()
    rows = []
    for rid in runs:
        rec = REGISTRY.get(rid) or {}
        rows.append(
            {
                "run_id": rid,
                "started_at": rec.get("started_at"),
                "duration_ms": rec.get("duration_ms"),
                "schema_version": rec.get("schema_version"),
                "fill_rate": (rec.get("summary") or {}).get("fill_rate"),
                "profit_total": (rec.get("summary") or {}).get("profit_total"),
            }
        )
    return templates.TemplateResponse("runs.html", {"request": request, "rows": rows})

