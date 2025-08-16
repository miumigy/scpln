from typing import List, Dict, Any
from fastapi import Body, HTTPException, Query
from app.api import app
from app.run_registry import REGISTRY

# 比較対象メトリクスのホワイトリスト（summary のキーに合わせる）
COMPARE_KEYS = [
    "fill_rate",
    "revenue_total",
    "cost_total",
    "penalty_total",
    "profit_total",
    "profit_per_day_avg",
    "store_demand_total",
    "store_sales_total",
    "customer_shortage_total",
]


def _pick(summary: Dict[str, Any]) -> Dict[str, float]:
    out = {}
    for k in COMPARE_KEYS:
        v = summary.get(k, 0.0)
        try:
            out[k] = float(v)
        except Exception:
            pass
    return out


@app.get("/runs")
def list_runs(detail: bool = Query(False)):
    """ラン一覧を返す。
    - detail=false（既定）: 軽量メタ+summary のみ
    - detail=true: フル（results/daily_profit_loss/cost_trace 含む）
    """
    if detail:
        return {"runs": REGISTRY.list()}
    ids = REGISTRY.list_ids()
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
def get_run(run_id: str, detail: bool = Query(False)):
    r = REGISTRY.get(run_id)
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    if detail:
        return r
    return {
        "run_id": r.get("run_id"),
        "started_at": r.get("started_at"),
        "duration_ms": r.get("duration_ms"),
        "schema_version": r.get("schema_version"),
        "summary": r.get("summary", {}),
    }


@app.post("/compare")
def compare_runs(body: Dict[str, Any] = Body(...)):
    ids: List[str] = body.get("run_ids") or []
    if not ids:
        raise HTTPException(status_code=400, detail="run_ids required")

    rows = []
    for rid in ids:
        r = REGISTRY.get(rid)
        if not r:
            raise HTTPException(status_code=404, detail=f"run not found: {rid}")
        rows.append({"run_id": rid, **_pick(r.get("summary", {}))})

    # 差分（先頭をベース）
    diffs = []
    if len(rows) >= 2:
        base = rows[0]
        for other in rows[1:]:
            diff_row = {"base": base["run_id"], "target": other["run_id"]}
            for k in COMPARE_KEYS:
                b = base.get(k, 0.0)
                t = other.get(k, 0.0)
                diff = t - b
                pct = (diff / b * 100.0) if b not in (0.0, None) else None
                diff_row[k] = {"abs": diff, "pct": pct}
            diffs.append(diff_row)

    return {"metrics": rows, "diffs": diffs}
