from typing import List, Dict, Any
import json
from fastapi import Body, HTTPException, Query, Request
import os
from app.api import app


def _get_registry():
    # 動的取得（テスト環境での再ロード・環境切替に対応）
    from app.run_registry import REGISTRY, _BACKEND  # type: ignore

    return REGISTRY, _BACKEND


from app.metrics import (
    RUNS_LIST_REQUESTS,
    RUNS_LIST_RETURNED,
    COMPARE_REQUESTS,
    COMPARE_DURATION,
)
import time
from app import db

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


def _pick(summary: Dict[str, Any], keys: List[str] | None = None) -> Dict[str, float]:
    out = {}
    use = keys or COMPARE_KEYS
    for k in use:
        v = summary.get(k, 0.0)
        try:
            out[k] = float(v)
        except Exception:
            pass
    return out


def _normalize_json(o: Any) -> str:
    try:
        if isinstance(o, str):
            return json.dumps(json.loads(o), ensure_ascii=False, sort_keys=True)
        return json.dumps(o, ensure_ascii=False, sort_keys=True)
    except Exception:
        return ""


def _resolve_config_id_from_json(cfg_json: Any) -> int | None:
    if not cfg_json:
        return None
    target = _normalize_json(cfg_json)
    if not target:
        return None
    try:
        for r in db.list_configs(limit=500) or []:
            rid = r.get("id")
            if not rid:
                continue
            rec = db.get_config(int(rid))
            if not rec or rec.get("json_text") is None:
                continue
            if _normalize_json(rec.get("json_text")) == target:
                return int(rid)
    except Exception:
        return None
    return None


@app.get("/runs")
def list_runs(
    detail: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=100),
    sort: str = Query("started_at"),
    order: str = Query("desc"),
    schema_version: str | None = Query(None),
    config_id: int | None = Query(None),
    config_version_id: int | None = Query(None),
    scenario_id: int | None = Query(None),
    plan_version_id: str | None = Query(None),
    scenario_name: str | None = Query(None),
):
    """ラン一覧を返す。
    - detail=false（既定）: 軽量メタ+summary のみ
    - detail=true: フル（results/daily_profit_loss/cost_trace 含む）
    """
    scenario_name_ids = None
    if scenario_name:
        name = scenario_name.strip().lower()
        scenario_name_ids = {
            row.get("id")
            for row in (db.list_scenarios(limit=2000) or [])
            if isinstance(row.get("name"), str)
            and name in row.get("name").lower()
        }
        if not scenario_name_ids:
            empty = {"runs": [], "total": 0, "offset": offset, "limit": limit or 0}
            return empty
    # サニタイズと limit 既定
    REGISTRY, _BACKEND = _get_registry()
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
            resp = REGISTRY.list_page(
                offset=offset,
                limit=limit,
                sort=sort,
                order=order,
                schema_version=schema_version,
                config_id=config_id,
                scenario_id=scenario_id,
                detail=True,
            )
            runs_list = resp.get("runs") or []
            if config_version_id is not None:
                runs_list = [
                    r
                    for r in runs_list
                    if r.get("config_version_id") == config_version_id
                ]
                resp["runs"] = runs_list
                resp["total"] = len(runs_list)
            if scenario_name_ids is not None:
                runs_list = [
                    r for r in runs_list if r.get("scenario_id") in scenario_name_ids
                ]
                resp["runs"] = runs_list
                resp["total"] = len(runs_list)
            if plan_version_id is not None:
                runs_list = [
                    r for r in runs_list if r.get("plan_version_id") == plan_version_id
                ]
                resp["runs"] = runs_list
                resp["total"] = len(runs_list)
            try:
                RUNS_LIST_REQUESTS.labels(detail="true", backend=_BACKEND).inc()
                RUNS_LIST_RETURNED.observe(len(resp.get("runs") or []))
            except Exception:
                pass
            return resp
        runs = REGISTRY.list()
        runs = _filter_and_sort(
            runs,
            sort,
            order,
            schema_version,
            config_id,
            config_version_id,
            scenario_id,
            plan_version_id,
            scenario_name_ids,
        )
        total = len(runs)
        sliced = runs[offset : offset + limit]
        try:
            RUNS_LIST_REQUESTS.labels(detail="true", backend=_BACKEND).inc()
            RUNS_LIST_RETURNED.observe(len(sliced))
        except Exception:
            pass
        return {"runs": sliced, "total": total, "offset": offset, "limit": limit}
    REGISTRY, _BACKEND = _get_registry()
    # DBバックエンド時は上限に応じたクリーンアップを実施（テスト・運用の安定化）
    try:
        import os as _os

        max_rows = int(_os.getenv("RUNS_DB_MAX_ROWS", "0") or 0)
        if max_rows > 0 and hasattr(REGISTRY, "cleanup_by_capacity"):
            REGISTRY.cleanup_by_capacity(max_rows)
    except Exception:
        pass
    ids = REGISTRY.list_ids()
    out = []
    if limit is None:
        limit = 50
    for rid in ids:
        rec = REGISTRY.get(rid) or {}
        cfg_id = rec.get("config_id")
        if cfg_id is None and rec.get("config_json") is not None:
            try:
                cfg_id = _resolve_config_id_from_json(rec.get("config_json"))
            except Exception:
                cfg_id = None
        out.append(
            {
                "run_id": rec.get("run_id"),
                "started_at": rec.get("started_at"),
                "duration_ms": rec.get("duration_ms"),
                "schema_version": rec.get("schema_version"),
                "summary": rec.get("summary", {}),
                "config_id": cfg_id,
                "config_version_id": rec.get("config_version_id"),
                "scenario_id": rec.get("scenario_id"),
                "plan_version_id": rec.get("plan_version_id"),
                "created_at": rec.get("created_at", rec.get("started_at")),
                "updated_at": rec.get(
                    "updated_at",
                    (rec.get("started_at") or 0) + (rec.get("duration_ms") or 0),
                ),
            }
        )
    # DBバックエンドはSQLでページング（ただし config_id 指定時は後方互換のためアプリ側でフィルタリングに切替）
    if (
        hasattr(REGISTRY, "list_page")
        and config_id is None
        and scenario_id is None
        and plan_version_id is None
    ):
        resp = REGISTRY.list_page(
            offset=offset,
            limit=limit,
            sort=sort,
            order=order,
            schema_version=schema_version,
            config_id=config_id,
            scenario_id=scenario_id,
            detail=False,
        )
        # backfill config_id using config_json when missing (DB backend lightweight mode includes config_json)
        try:
            runs_list = resp.get("runs", []) or []
            for r in runs_list:
                if r.get("config_id") is None and r.get("config_json") is not None:
                    rid2 = _resolve_config_id_from_json(r.get("config_json"))
                    if rid2 is not None:
                        r["config_id"] = rid2
        except Exception:
            pass
        runs_list = resp.get("runs") or []
        if config_version_id is not None:
            runs_list = [
                r for r in runs_list if r.get("config_version_id") == config_version_id
            ]
            resp["runs"] = runs_list
            resp["total"] = len(runs_list)
        try:
            RUNS_LIST_REQUESTS.labels(detail="false", backend=_BACKEND).inc()
            RUNS_LIST_RETURNED.observe(len(resp.get("runs") or []))
        except Exception:
            pass
        return resp
    elif hasattr(REGISTRY, "list_ids"):
        # 後方互換: DBでも config_id / scenario_id 指定時は全件からアプリ側でフィルタ（config_json を用いた推定を含む）
        ids2 = REGISTRY.list_ids()
        rows2: List[Dict[str, Any]] = []
        for rid in ids2:
            rec = REGISTRY.get(rid) or {}
            cfg_id2 = rec.get("config_id")
            if cfg_id2 is None and rec.get("config_json") is not None:
                try:
                    cfg_id2 = _resolve_config_id_from_json(rec.get("config_json"))
                except Exception:
                    cfg_id2 = None
            rows2.append(
                {
                    "run_id": rec.get("run_id"),
                    "started_at": rec.get("started_at"),
                    "duration_ms": rec.get("duration_ms"),
                    "schema_version": rec.get("schema_version"),
                    "summary": rec.get("summary", {}),
                    "config_id": cfg_id2,
                    "config_version_id": rec.get("config_version_id"),
                    "scenario_id": rec.get("scenario_id"),
                    "plan_version_id": rec.get("plan_version_id"),
                    "created_at": rec.get("created_at", rec.get("started_at")),
                    "updated_at": rec.get(
                        "updated_at",
                        (rec.get("started_at") or 0) + (rec.get("duration_ms") or 0),
                    ),
                }
            )
        rows2 = _filter_and_sort(
            rows2,
            sort,
            order,
            schema_version,
            config_id,
            config_version_id,
            scenario_id,
            plan_version_id,
            scenario_name_ids,
        )
        total2 = len(rows2)
        rows2 = rows2[offset : offset + limit]
        try:
            RUNS_LIST_REQUESTS.labels(detail="false", backend=_BACKEND).inc()
            RUNS_LIST_RETURNED.observe(len(rows2))
        except Exception:
            pass
        return {"runs": rows2, "total": total2, "offset": offset, "limit": limit}
    out = _filter_and_sort(
        out,
        sort,
        order,
        schema_version,
        config_id,
        config_version_id,
        scenario_id,
        plan_version_id,
        scenario_name_ids,
    )
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
    REGISTRY, _ = _get_registry()
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
    keys: str | None = Query(None),
):
    _t0 = time.monotonic()
    REGISTRY, _ = _get_registry()
    ids: List[str] = body.get("run_ids") or []
    if not ids:
        raise HTTPException(status_code=400, detail="run_ids required")
    if base_id and base_id in ids:
        ids = [base_id] + [x for x in ids if x != base_id]

    # keys filter
    use_keys = COMPARE_KEYS
    if keys:
        req = [x.strip() for x in keys.split(",") if x.strip()]
        filt = [k for k in req if k in COMPARE_KEYS]
        if filt:
            use_keys = filt

    rows = []
    for rid in ids:
        r = REGISTRY.get(rid)
        if not r:
            raise HTTPException(status_code=404, detail=f"run not found: {rid}")
        rows.append({"run_id": rid, **_pick(r.get("summary", {}), use_keys)})

    # 差分（先頭をベース）
    diffs = []
    if len(rows) >= 2:
        base = rows[0]
        for other in rows[1:]:
            diff_row: Dict[str, Any] = {
                "base": base["run_id"],
                "target": other["run_id"],
            }
            for k in use_keys:
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
    # 常にkeysを含める（明示性のため）
    resp["keys"] = use_keys
    try:
        COMPARE_REQUESTS.labels(
            threshold=str(threshold is not None).lower(),
            keys=str(keys is not None).lower(),
            runs=str(len(ids)),
            base_set=str(bool(base_id)).lower(),
        ).inc()
        COMPARE_DURATION.observe(time.monotonic() - _t0)
    except Exception:
        pass
    return resp


@app.delete("/runs/{run_id}")
def delete_run(run_id: str, request: Request):
    REGISTRY, _ = _get_registry()
    r = REGISTRY.get(run_id)
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    # RBACライト: 有効時はX-Roleヘッダ（planner/adminなど）を要求
    if (
        os.getenv("RBAC_ENABLED", "0") == "1"
        or os.getenv("RBAC_DELETE_ENABLED", "0") == "1"
    ):
        role = request.headers.get("X-Role", "")
        allowed = {
            x.strip()
            for x in (os.getenv("RBAC_DELETE_ROLES", "planner,admin").split(","))
            if x.strip()
        }
        if role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden: role not allowed")
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
    config_version_id: int | None,
    scenario_id: int | None,
    plan_version_id: str | None,
    scenario_name_ids: set[int] | None,
) -> List[Dict[str, Any]]:
    def f(x: Dict[str, Any]) -> bool:
        if schema_version is not None and x.get("schema_version") != schema_version:
            return False
        if config_id is not None and x.get("config_id") != config_id:
            return False
        if (
            config_version_id is not None
            and x.get("config_version_id") != config_version_id
        ):
            return False
        if scenario_id is not None and x.get("scenario_id") != scenario_id:
            return False
        if plan_version_id is not None and x.get("plan_version_id") != plan_version_id:
            return False
        if (
            scenario_name_ids is not None
            and x.get("scenario_id") not in scenario_name_ids
        ):
            return False
        return True

    out = [r for r in rows if f(r)]
    reverse = order == "desc"
    out.sort(key=lambda x: (x.get(sort) is None, x.get(sort)), reverse=reverse)
    return out
