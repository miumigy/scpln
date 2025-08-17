from pathlib import Path
from fastapi import Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.api import app
from app.utils import ms_to_jst_str
from app.db import list_configs, get_config, create_config, update_config, delete_config

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/ui/configs", response_class=HTMLResponse)
def ui_configs_list(request: Request):
    rows = list_configs()
    # 表示用にJST日時の整形カラムを付与
    for r in rows:
        r["updated_at_str"] = ms_to_jst_str(r.get("updated_at"))
        r["created_at_str"] = ms_to_jst_str(r.get("created_at"))
    return templates.TemplateResponse(
        "configs_list.html", {"request": request, "rows": rows, "subtitle": "設定マスタ"}
    )


@app.get("/ui/configs/new", response_class=HTMLResponse)
def ui_configs_new(request: Request):
    return templates.TemplateResponse(
        "configs_edit.html", {"request": request, "mode": "create", "rec": {"name": "", "json_text": ""}, "subtitle": "設定マスタ"}
    )


@app.post("/ui/configs/new")
def ui_configs_create(name: str = Form(...), json_text: str = Form(...)):
    new_id = create_config(name, json_text)
    return RedirectResponse(url="/ui/configs", status_code=303)


@app.get("/ui/configs/{cfg_id}/edit", response_class=HTMLResponse)
def ui_configs_edit(request: Request, cfg_id: int):
    rec = get_config(cfg_id)
    if not rec:
        raise HTTPException(status_code=404, detail="config not found")
    return templates.TemplateResponse(
        "configs_edit.html", {"request": request, "mode": "edit", "rec": rec, "subtitle": "設定マスタ"}
    )


@app.post("/ui/configs/{cfg_id}/edit")
def ui_configs_update(cfg_id: int, name: str = Form(...), json_text: str = Form(...)):
    if not get_config(cfg_id):
        raise HTTPException(status_code=404, detail="config not found")
    update_config(cfg_id, name, json_text)
    return RedirectResponse(url="/ui/configs", status_code=303)


@app.post("/ui/configs/{cfg_id}/delete")
def ui_configs_delete(cfg_id: int):
    if not get_config(cfg_id):
        raise HTTPException(status_code=404, detail="config not found")
    delete_config(cfg_id)
    return RedirectResponse(url="/ui/configs", status_code=303)
