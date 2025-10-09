from app.api import app
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import db
import logging

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/ui/scenarios", response_class=HTMLResponse)
def ui_scenarios(request: Request):
    rows = db.list_scenarios(500)
    return templates.TemplateResponse(
        request,
        "scenarios.html",
        {
            "rows": rows,
            "subtitle": "Scenarios",
            "doc_link": "/docs/run_registry_operations.md",
        },
    )


@app.post("/ui/scenarios", response_class=HTMLResponse)
def ui_scenarios_post(
    request: Request,
    name: str = Form(""),
    parent_id: str = Form(""),
    tag: str = Form(""),
    description: str = Form(""),
):
    try:
        pid = int(parent_id) if parent_id else None
    except (ValueError, TypeError):
        pid = None
    db.create_scenario(
        name=name or "(no name)",
        parent_id=pid,
        tag=(tag or None),
        description=(description or None),
    )
    return RedirectResponse(url="/ui/scenarios", status_code=303)


@app.post("/ui/scenarios/{sid}/run")
def ui_scenarios_run(request: Request, sid: int, config_id: int = Form(...)):
    return PlainTextResponse(
        "Scenario-based simulation has been retired. Use Plan & Run via /ui/plans.",
        status_code=403,
    )


@app.post("/ui/scenarios/{sid}/edit")
def ui_scenarios_edit(
    request: Request,
    sid: int,
    name: str = Form(""),
    parent_id: str | None = Form(None),
    tag: str = Form(""),
    description: str = Form(""),
    locked: str | None = Form(None),
):
    # 正規化
    fields: dict = {}
    if name:
        fields["name"] = name
    # parent_id は空なら None
    try:
        if parent_id is not None and str(parent_id).strip() != "":
            fields["parent_id"] = int(parent_id)
        else:
            fields["parent_id"] = None
    except Exception:
        fields["parent_id"] = None
    fields["tag"] = tag or None
    fields["description"] = description or None
    # チェックボックス: 値があれば True
    fields["locked"] = 1 if (locked is not None) else 0
    try:
        if not db.get_scenario(sid):
            return RedirectResponse(url="/ui/scenarios", status_code=303)
        db.update_scenario(sid, **fields)
    except Exception:
        logging.exception("ui_scenarios_edit_failed")
    return RedirectResponse(url="/ui/scenarios", status_code=303)


@app.post("/ui/scenarios/{sid}/delete")
def ui_scenarios_delete(request: Request, sid: int):
    try:
        if db.get_scenario(sid):
            db.delete_scenario(sid)
    except Exception:
        logging.exception("ui_scenarios_delete_failed")
    return RedirectResponse(url="/ui/scenarios", status_code=303)
