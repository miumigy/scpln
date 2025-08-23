from typing import Dict, Any
from fastapi import Body, HTTPException
from app.api import app
from app import db


@app.get("/hierarchy/product")
def get_product_hierarchy():
    return {"mapping": db.get_product_hierarchy()}


@app.post("/hierarchy/product")
def post_product_hierarchy(body: Dict[str, Any] = Body(...)):
    mapping = body.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="mapping must be an object")
    db.set_product_hierarchy(mapping)
    return {"status": "ok", "size": len(mapping)}


@app.get("/hierarchy/location")
def get_location_hierarchy():
    return {"mapping": db.get_location_hierarchy()}


@app.post("/hierarchy/location")
def post_location_hierarchy(body: Dict[str, Any] = Body(...)):
    mapping = body.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="mapping must be an object")
    db.set_location_hierarchy(mapping)
    return {"status": "ok", "size": len(mapping)}
