from app.api import app
import json
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.run_registry import REGISTRY
from app.utils import ms_to_jst_str
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


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
                "started_at_str": ms_to_jst_str(rec.get("started_at")),
                "duration_ms": rec.get("duration_ms"),
                "schema_version": rec.get("schema_version"),
                "config_id": rec.get("config_id"),
                "fill_rate": (rec.get("summary") or {}).get("fill_rate"),
                "profit_total": (rec.get("summary") or {}).get("profit_total"),
            }
        )
    return templates.TemplateResponse(
        "runs.html", {"request": request, "rows": rows, "subtitle": "Run Viewer"}
    )


@app.get("/ui/runs/{run_id}", response_class=HTMLResponse)
def ui_run_detail(request: Request, run_id: str):
    rec = REGISTRY.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    summary = rec.get("summary") or {}
    counts = {
        "results_len": len(rec.get("results") or []),
        "pl_len": len(rec.get("daily_profit_loss") or []),
        "trace_len": len(rec.get("cost_trace") or []),
    }
    cfg_id = rec.get("config_id")
    cfg_json = rec.get("config_json")
    try:
        cfg_json_str = json.dumps(cfg_json, ensure_ascii=False, indent=2) if cfg_json is not None else ""
    except Exception:
        cfg_json_str = ""
    return templates.TemplateResponse(
        "run_detail.html",
        {
            "request": request,
            "run_id": run_id,
            "summary": summary,
            "counts": counts,
            "config_id": cfg_id,
            "config_json_str": cfg_json_str,
            "subtitle": "Run Viewer",
        },
    )
