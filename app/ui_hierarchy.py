from app.api import app
from fastapi import Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import json
from app import db

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/ui/hierarchy", response_class=HTMLResponse)
def ui_hierarchy(request: Request):
    pmap = db.get_product_hierarchy()
    lmap = db.get_location_hierarchy()
    return templates.TemplateResponse(
        "hierarchy.html",
        {
            "request": request,
            "pjson": json.dumps(pmap, ensure_ascii=False, indent=2),
            "ljson": json.dumps(lmap, ensure_ascii=False, indent=2),
            "subtitle": "Hierarchy Master",
        },
    )


@app.post("/ui/hierarchy", response_class=HTMLResponse)
def ui_hierarchy_post(request: Request, product_json: str = Form(""), location_json: str = Form("")):
    try:
        if product_json:
            db.set_product_hierarchy(json.loads(product_json))
        if location_json:
            db.set_location_hierarchy(json.loads(location_json))
    except Exception:
        pass
    return ui_hierarchy(request)

