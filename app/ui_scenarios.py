from app.api import app
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import db
from app.jobs import JOB_MANAGER
import json
import logging

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/ui/scenarios", response_class=HTMLResponse)
def ui_scenarios(request: Request):
    rows = db.list_scenarios(500)
    cfgs = db.list_configs(200)
    return templates.TemplateResponse(
        "scenarios.html",
        {"request": request, "rows": rows, "configs": cfgs, "subtitle": "Scenarios"},
    )


@app.post("/ui/scenarios", response_class=HTMLResponse)
def ui_scenarios_post(
    request: Request,
    name: str = Form(""),
    parent_id: int | None = Form(None),
    tag: str = Form(""),
    description: str = Form(""),
):
    sid = db.create_scenario(
        name=name or "(no name)",
        parent_id=parent_id,
        tag=(tag or None),
        description=(description or None),
    )
    return RedirectResponse(url="/ui/scenarios", status_code=303)


@app.post("/ui/scenarios/{sid}/run")
def ui_scenarios_run(request: Request, sid: int, config_id: int = Form(...)):
    logging.warning(f"--- DEBUG: ui_scenarios_run called with config_id={config_id}")
    rec = db.get_config(int(config_id))
    logging.warning(f"--- DEBUG: db.get_config returned: {rec}")
    # 取得した設定JSONを使ってジョブ実行。scenario_id/config_id を付与。
    rec = db.get_config(int(config_id))
    if not rec:
        return PlainTextResponse("config not found", status_code=404)
    try:
        payload = json.loads(rec.get("json_text") or "{}")
    except Exception:
        return PlainTextResponse("invalid config json", status_code=400)
    if not isinstance(payload, dict):
        return PlainTextResponse("invalid config json", status_code=400)
    # 付与（jobs.py 側でpopしRunへ保存される）
    payload["config_id"] = int(config_id)
    payload["scenario_id"] = int(sid)
    job_id = JOB_MANAGER.submit_simulation(payload)
    # ジョブ一覧へ遷移
    return RedirectResponse(url=f"/ui/jobs", status_code=303)
