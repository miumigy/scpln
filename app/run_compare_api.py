from typing import List, Dict, Any
from fastapi import Body, HTTPException, Query
from app.api import app
from app.run_registry import REGISTRY
from app.run_registry import _BACKEND  # type: ignore
from app.metrics import RUNS_LIST_REQUESTS, RUNS_LIST_RETURNED

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
def list_runs(
    detail: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=100),
    sort: str = Query("started_at"),
    order: str = Query("desc"),
    schema_version: str | None = Query(None),
    config_id: int | None = Query(None),
):
    """ラン一覧を返す。
    - detail=false（既定）: 軽量メタ+summary のみ
    - detail=true: フル（results/daily_profit_loss/cost_trace 含む）
    """
    # サニタイズと limit 既定
    sort_keys = {"started_at", "duration_ms", "schema_version"}
    if sort not in sort_keys:
        sort = "started_at"
    order = order.lower()
    if order not in ("asc", "desc"):
        order = "desc"
    # 既定の limit を detail に応じて切替。detail=true は既定10、かつ >10 は拒否。
    if detail:
        if limit is None:
            limit = 10
        elif limit > 10:
            raise HTTPException(
                status_code=400,
                detail="detail=true の場合は limit <= 10 にしてください",
            )
        # DBバックエンドはSQLでページング
        if hasattr(REGISTRY, "list_page"):
            return REGISTRY.list_page(
                offset=offset,
                limit=limit,
                sort=sort,
                order=order,
                schema_version=schema_version,
                config_id=config_id,
                detail=True,
            )
        runs = REGISTRY.list()
        runs = _filter_and_sort(runs, sort, order, schema_version, config_id)
        total = len(runs)
        sliced = runs[offset : offset + limit]
        try:
            RUNS_LIST_REQUESTS.labels(detail="true", backend=_BACKEND).inc()
            RUNS_LIST_RETURNED.observe(len(sliced))
        except Exception:
            pass
        return {"runs": sliced, "total": total, "offset": offset, "limit": limit}
    ids = REGISTRY.list_ids()
    out = []
    if limit is None:
        limit = 50
    for rid in ids:
        rec = REGISTRY.get(rid) or {}
        out.append(
            {
                "run_id": rec.get("run_id"),
                "started_at": rec.get("started_at"),
                "duration_ms": rec.get("duration_ms"),
                "schema_version": rec.get("schema_version"),
                "summary": rec.get("summary", {}),
                "config_id": rec.get("config_id"),
                "created_at": rec.get("created_at", rec.get("started_at")),
                "updated_at": rec.get("updated_at", (rec.get("started_at") or 0) + (rec.get("duration_ms") or 0)),
            }
        )
    # DBバックエンドはSQLでページング
    if hasattr(REGISTRY, "list_page"):
        resp = REGISTRY.list_page(
            offset=offset,
            limit=limit,
            sort=sort,
            order=order,
            schema_version=schema_version,
            config_id=config_id,
            detail=False,
        )
        try:
            RUNS_LIST_REQUESTS.labels(detail="false", backend=_BACKEND).inc()
            RUNS_LIST_RETURNED.observe(len(resp.get("runs") or []))
        except Exception:
            pass
        return resp
    out = _filter_and_sort(out, sort, order, schema_version, config_id)
    total = len(out)
    out = out[offset : offset + limit]
    try:
        RUNS_LIST_REQUESTS.labels(detail="false", backend=_BACKEND).inc()
        RUNS_LIST_RETURNED.observe(len(out))
    except Exception:
        pass
    return {"runs": out, "total": total, "offset": offset, "limit": limit}


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
def compare_runs(
    body: Dict[str, Any] = Body(...),
    threshold: float | None = Query(None),
    base_id: str | None = Query(None),
):
    ids: List[str] = body.get("run_ids") or []
    if not ids:
        raise HTTPException(status_code=400, detail="run_ids required")
    if base_id and base_id in ids:
        ids = [base_id] + [x for x in ids if x != base_id]

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
            diff_row: Dict[str, Any] = {"base": base["run_id"], "target": other["run_id"]}
            for k in COMPARE_KEYS:
                b = base.get(k, 0.0)
                t = other.get(k, 0.0)
                diff = t - b
                pct = (diff / b * 100.0) if b not in (0.0, None) else None
                hit = None
                if threshold is not None and pct is not None:
                    hit = abs(pct) >= threshold
                diff_row[k] = {"abs": diff, "pct": pct, "hit": hit}
            diffs.append(diff_row)
    resp: Dict[str, Any] = {"metrics": rows, "diffs": diffs}
    if threshold is not None:
        resp["threshold"] = threshold
    if base_id:
        resp["base_id"] = base_id
    return resp


@app.delete("/runs/{run_id}")
def delete_run(run_id: str):
    r = REGISTRY.get(run_id)
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    # DB/メモリ双方に対応
    if hasattr(REGISTRY, "delete"):
        REGISTRY.delete(run_id)
    return {"status": "deleted", "run_id": run_id}


def _filter_and_sort(
    rows: List[Dict[str, Any]],
    sort: str,
    order: str,
    schema_version: str | None,
    config_id: int | None,
) -> List[Dict[str, Any]]:
    def f(x: Dict[str, Any]) -> bool:
        if schema_version is not None and x.get("schema_version") != schema_version:
            return False
        if config_id is not None and x.get("config_id") != config_id:
            return False
        return True

    out = [r for r in rows if f(r)]
    reverse = order == "desc"
    out.sort(key=lambda x: (x.get(sort) is None, x.get(sort)), reverse=reverse)
    return out
