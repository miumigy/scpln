from typing import Any, Dict, Optional
from fastapi import Body, HTTPException
from app.api import app
from app import db


@app.get("/scenarios")
def list_scenarios(limit: int = 200):
    return {"scenarios": db.list_scenarios(limit)}


@app.get("/scenarios/{sid}")
def get_scenario(sid: int):
    row = db.get_scenario(sid)
    if not row:
        raise HTTPException(status_code=404, detail="scenario not found")
    return row


@app.post("/scenarios")
def post_scenario(body: Dict[str, Any] = Body(...)):
    sid = db.create_scenario(
        name=body.get("name") or "(no name)",
        parent_id=body.get("parent_id"),
        tag=body.get("tag"),
        description=body.get("description"),
        locked=bool(body.get("locked") or False),
    )
    return {"id": sid}


@app.put("/scenarios/{sid}")
def put_scenario(sid: int, body: Dict[str, Any] = Body(...)):
    if not db.get_scenario(sid):
        raise HTTPException(status_code=404, detail="scenario not found")
    db.update_scenario(sid, **body)
    return {"status": "ok"}


@app.delete("/scenarios/{sid}")
def delete_scenario(sid: int):
    if not db.get_scenario(sid):
        raise HTTPException(status_code=404, detail="scenario not found")
    db.delete_scenario(sid)
    return {"status": "deleted", "id": sid}

