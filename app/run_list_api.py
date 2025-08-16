from fastapi import HTTPException
from app.api import app
from app.run_registry import REGISTRY


@app.get("/runs")
def list_runs():
    ids = REGISTRY.list_ids()
    # 軽量にするため、一覧はメタ情報のみ
    out = []
    for rid in ids:
        rec = REGISTRY.get(rid) or {}
        out.append(
            {
                "run_id": rec.get("run_id"),
                "started_at": rec.get("started_at"),
                "duration_ms": rec.get("duration_ms"),
                "schema_version": rec.get("schema_version"),
                "summary": rec.get("summary", {}),
            }
        )
    return {"runs": out}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    rec = REGISTRY.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    # 明細は summary とメタのみ返す（results等は重いので必要時に）
    return {
        "run_id": rec.get("run_id"),
        "started_at": rec.get("started_at"),
        "duration_ms": rec.get("duration_ms"),
        "schema_version": rec.get("schema_version"),
        "summary": rec.get("summary", {}),
    }

