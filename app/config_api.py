import json
from fastapi import Form, HTTPException
from app.api import app
from app.db import list_configs, get_config, create_config, update_config, delete_config


@app.get("/configs")
def configs_list():
    rows = list_configs()
    return {"configs": rows}


@app.get("/configs/{cfg_id}")
def configs_get(cfg_id: int):
    rec = get_config(cfg_id)
    if not rec:
        raise HTTPException(status_code=404, detail="config not found")
    try:
        cfg = json.loads(rec.get("json_text") or "{}")
    except Exception:
        cfg = None
    return {
        "id": rec["id"],
        "name": rec["name"],
        "config": cfg,
        "json_text": rec.get("json_text"),
        "created_at": rec.get("created_at"),
        "updated_at": rec.get("updated_at"),
    }


@app.post("/configs")
def configs_create(name: str = Form(...), json_text: str = Form(...)):
    try:
        json.loads(json_text)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON in json_text")
    new_id = create_config(name, json_text)
    return {"id": new_id}


@app.put("/configs/{cfg_id}")
def configs_update(cfg_id: int, name: str = Form(...), json_text: str = Form(...)):
    if not get_config(cfg_id):
        raise HTTPException(status_code=404, detail="config not found")
    try:
        json.loads(json_text)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON in json_text")
    update_config(cfg_id, name, json_text)
    return {"ok": True}


@app.delete("/configs/{cfg_id}")
def configs_delete(cfg_id: int):
    if not get_config(cfg_id):
        raise HTTPException(status_code=404, detail="config not found")
    delete_config(cfg_id)
    return {"ok": True}
