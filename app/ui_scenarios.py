from app.api import app
from fastapi import Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import db

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/ui/scenarios", response_class=HTMLResponse)
def ui_scenarios(request: Request):
    rows = db.list_scenarios(500)
    return templates.TemplateResponse(
        "scenarios.html",
        {"request": request, "rows": rows, "subtitle": "Scenarios"},
    )


@app.post("/ui/scenarios", response_class=HTMLResponse)
def ui_scenarios_post(request: Request, name: str = Form(""), parent_id: int | None = Form(None), tag: str = Form(""), description: str = Form("")):
    sid = db.create_scenario(name=name or "(no name)", parent_id=parent_id, tag=(tag or None), description=(description or None))
    return RedirectResponse(url="/ui/scenarios", status_code=303)

