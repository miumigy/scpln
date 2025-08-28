from app.api import app
from fastapi import Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List
from pathlib import Path
import csv
import io
from app import db as _db


def _get_registry():
    from app.run_registry import REGISTRY  # type: ignore

    return REGISTRY


def _get_rec(run_id: str):
    rec = _get_registry().get(run_id)
    if rec:
        return rec
    # fallback to DB
    try:
        with _db._conn() as c:  # type: ignore[attr-defined]
            row = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            import json as _json

            return {
                "run_id": row["run_id"],
                "summary": _json.loads(row["summary"] or "{}"),
                "results": _json.loads(row["results"] or "[]"),
                "daily_profit_loss": _json.loads(row["daily_profit_loss"] or "[]"),
                "cost_trace": _json.loads(row["cost_trace"] or "[]"),
                "config_id": row["config_id"],
                "scenario_id": row["scenario_id"],
            }
    except Exception:
        return None


_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.post("/ui/compare", response_class=HTMLResponse)
def ui_compare(
    request: Request,
    run_ids: str = Form(...),
    base_id: str | None = Form(None),
    threshold: str | None = Form(None),
    keys: str | None = Form(None),
):
    ids: List[str] = [x.strip() for x in run_ids.split(",") if x.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Need 2 or more run_ids")

    # base_id が指定されていれば先頭へ移動
    if base_id and base_id in ids:
        ids = [base_id] + [x for x in ids if x != base_id]

    # 簡易実装: REGISTRY から横並び & 差分（先頭基準）
    REGISTRY = _get_registry()

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

    # keys filter
    use_keys = COMPARE_KEYS
    if keys:
        req = [x.strip() for x in keys.split(",") if x.strip()]
        filt = [k for k in req if k in COMPARE_KEYS]
        if filt:
            use_keys = filt

    rows = []
    for rid in ids:
        rec = _get_rec(rid)
        if not rec:
            raise HTTPException(status_code=404, detail=f"run not found: {rid}")
        s = rec.get("summary") or {}
        row = {"run_id": rid}
        for k in use_keys:
            v = s.get(k, 0.0)
            try:
                row[k] = float(v)
            except Exception:
                row[k] = None
        rows.append(row)

    # 閾値（%）
    try:
        th_pct = float(threshold) if threshold is not None and threshold != "" else None
    except Exception:
        th_pct = None

    diffs = []
    if len(rows) >= 2:
        base = rows[0]
        for other in rows[1:]:
            diff = {"base": base["run_id"], "target": other["run_id"]}
            for k in use_keys:
                b = base.get(k) or 0.0
                t = other.get(k) or 0.0
                d = t - b
                pct = (d / b * 100.0) if b else None
                diff[k] = {"abs": d, "pct": pct}
            diffs.append(diff)

    return templates.TemplateResponse(
        "compare.html",
        {
            "request": request,
            "rows": rows,
            "diffs": diffs,
            "keys": use_keys,
            "run_ids_str": ",".join([r["run_id"] for r in rows]),
            "base_id": rows[0]["run_id"] if rows else None,
            "threshold": th_pct,
            "keys_str": ",".join(use_keys),
            "base_scenario": None,
            "target_scenarios": None,
        },
    )


def _latest_runs_by_scenarios(
    base_scenario: int, target_scenarios: List[int], limit: int = 1
) -> List[str]:
    out: List[str] = []
    limit = max(1, int(limit or 1))

    def _latest_for_many(sid: int, n: int) -> List[str]:
        try:
            REGISTRY = _get_registry()
            if hasattr(REGISTRY, "list_page"):
                # DBバックエンド：シナリオIDで直接ページング取得
                resp = REGISTRY.list_page(
                    offset=0,
                    limit=n,
                    sort="started_at",
                    order="desc",
                    schema_version=None,
                    config_id=None,
                    scenario_id=sid,
                    detail=False,
                )
                runs = resp.get("runs") or []
                return [r.get("run_id") for r in runs if r.get("run_id")]
            else:
                # メモリ実装: list_ids は新しい順を返す想定
                ids = getattr(REGISTRY, "list_ids", lambda: [])()
                matched = []
                for rid in ids:
                    rec = _get_rec(rid) or {}
                    if rec.get("scenario_id") == sid:
                        matched.append(rid)
                        if len(matched) >= n:
                            break
                return matched
        except Exception:
            return []

    out.extend(_latest_for_many(int(base_scenario), limit))
    for t in target_scenarios:
        out.extend(_latest_for_many(int(t), limit))
    # 重複除去（順序保持）
    seen = set()
    uniq = []
    for rid in out:
        if rid in seen:
            continue
        seen.add(rid)
        uniq.append(rid)
    return uniq


@app.get("/ui/compare/preset", response_class=HTMLResponse)
def ui_compare_preset(
    request: Request,
    base_scenario: int,
    target_scenarios: str,
    limit: int = 1,
    threshold: float | None = None,
    keys: str | None = None,
):
    # 入力の正規化
    try:
        targets = [int(x) for x in (target_scenarios or "").split(",") if x.strip()]
    except Exception:
        targets = []
    if not targets:
        raise HTTPException(status_code=400, detail="target_scenarios required")

    # REGISTRY からシナリオごとの最新Runを厳密に取得（メモリ/DBのいずれでも動作）
    REGISTRY = _get_registry()
    want = [int(base_scenario), *targets]
    ids: List[str] = []

    # まず最新マップ（run_latest）から引く（各シナリオの直近Run）
    try:
        from app import run_latest as _run_latest

        for sid in want:
            picks = _run_latest.latest(int(sid), limit=1)
            if picks:
                ids.append(picks[0])
    except Exception:
        pass

    # 近傍のRunを広く集めてから、シナリオごとの最新を選ぶ（順序は新しい→古い）
    recent: List[dict] = []
    try:
        # 1) REGISTRY.list()（メモリ/DB双方で有用）
        recent.extend(getattr(REGISTRY, "list", lambda: [])() or [])
    except Exception:
        pass
    try:
        # 1.5) メモリREGISTRYの内部（_runs）を直接参照（順序は started_at で後段整列）
        if hasattr(REGISTRY, "_runs"):
            vals = list(getattr(REGISTRY, "_runs").values())
            recent.extend(vals)
    except Exception:
        pass
    try:
        # 2) REGISTRY.list_page（DBバックエンドの軽量メタ）
        if hasattr(REGISTRY, "list_page"):
            resp = REGISTRY.list_page(
                offset=0,
                limit=200,
                sort="started_at",
                order="desc",
                schema_version=None,
                config_id=None,
                scenario_id=None,
                detail=False,
            )
            recent.extend(resp.get("runs") or [])
    except Exception:
        pass
    try:
        # 3) SQLite直クエリ（最後の保険）
        with _db._conn() as c:  # type: ignore[attr-defined]
            rows = c.execute(
                "SELECT run_id, scenario_id, started_at FROM runs ORDER BY started_at DESC, run_id DESC LIMIT 200"
            ).fetchall()
            for r in rows:
                recent.append(
                    {
                        "run_id": r["run_id"],
                        "scenario_id": r["scenario_id"],
                        "started_at": (
                            r.get("started_at")
                            if hasattr(r, "get")
                            else r["started_at"]
                        ),
                    }
                )
    except Exception:
        pass
    # 重複除去（最新優先）
    seen = set()
    dedup: List[dict] = []
    # started_at の降順に整列（欠損は後回し）
    recent_sorted = sorted(
        (recent or []),
        key=lambda r: (r.get("started_at") is None, r.get("started_at") or 0),
        reverse=True,
    )
    for rec in recent_sorted:
        rid = (rec or {}).get("run_id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        dedup.append(rec)

    for sid in want:
        chosen: str | None = None
        for rec in dedup:
            try:
                if rec.get("scenario_id") is None:
                    continue
                if int(rec.get("scenario_id")) == int(sid):
                    chosen = rec.get("run_id")
                    break
            except Exception:
                continue
        if chosen and chosen not in ids:
            ids.append(chosen)

    if len(ids) < len(want):
        # 指定された全シナリオについてRunが見つからない場合は404
        raise HTTPException(status_code=404, detail="runs not found for scenarios")
    # reuse ui_compare path by constructing rows/diffs here
    # keys filter
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
    use_keys = COMPARE_KEYS
    if keys:
        req = [x.strip() for x in keys.split(",") if x.strip()]
        filt = [k for k in req if k in COMPARE_KEYS]
        if filt:
            use_keys = filt
    rows = []
    for rid in ids:
        rec = _get_rec(rid)
        s = (rec.get("summary") or {}) if rec else {}
        row = {"run_id": rid}
        for k in use_keys:
            try:
                row[k] = float(s.get(k, 0.0))
            except Exception:
                row[k] = None
        rows.append(row)
    diffs = []
    if len(rows) >= 2:
        base_id = rows[0]["run_id"]
        base = rows[0]
        for other in rows[1:]:
            diff = {"base": base_id, "target": other["run_id"]}
            for k in use_keys:
                b = base.get(k) or 0.0
                t = other.get(k) or 0.0
                d = t - b
                pct = (d / b * 100.0) if b else None
                diff[k] = {"abs": d, "pct": pct}
            diffs.append(diff)
    return templates.TemplateResponse(
        "compare.html",
        {
            "request": request,
            "rows": rows,
            "diffs": diffs,
            "keys": use_keys,
            # rowsが空でも run_ids は表示できるよう、ids を直接連結
            "run_ids_str": ",".join(ids),
            "base_id": rows[0]["run_id"] if rows else None,
            "threshold": threshold,
            "keys_str": ",".join(use_keys),
            "base_scenario": int(base_scenario),
            "target_scenarios": target_scenarios,
        },
    )


@app.get("/ui/compare/metrics.csv")
def ui_compare_metrics_csv(request: Request, run_ids: str, base_id: str | None = None):
    ids: List[str] = [x.strip() for x in (run_ids or "").split(",") if x.strip()]
    if len(ids) < 1:
        raise HTTPException(status_code=400, detail="run_ids required")
    if base_id and base_id in ids:
        ids = [base_id] + [x for x in ids if x != base_id]
    from app.run_registry import REGISTRY

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
    rows = []
    for rid in ids:
        rec = REGISTRY.get(rid)
        if not rec:
            raise HTTPException(status_code=404, detail=f"run not found: {rid}")
        s = rec.get("summary") or {}
        row = {"run_id": rid}
        for k in COMPARE_KEYS:
            v = s.get(k, 0.0)
            try:
                row[k] = float(v)
            except Exception:
                row[k] = None
        rows.append(row)
    buf = io.StringIO()
    # meta lines
    import datetime as _dt

    buf.write(f"# generated_at: {_dt.datetime.utcnow().isoformat()}Z\n")
    if base_id:
        buf.write(f"# base_id: {base_id}\n")
    w = csv.DictWriter(buf, fieldnames=["run_id", *COMPARE_KEYS])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    headers = {"Content-Disposition": "attachment; filename=compare_metrics.csv"}
    from fastapi import Response

    return Response(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers
    )


@app.get("/ui/compare/diffs.csv")
def ui_compare_diffs_csv(
    request: Request,
    run_ids: str,
    base_id: str | None = None,
    threshold: float | None = None,
):
    ids: List[str] = [x.strip() for x in (run_ids or "").split(",") if x.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Need 2 or more run_ids")
    if base_id and base_id in ids:
        ids = [base_id] + [x for x in ids if x != base_id]
    from app.run_registry import REGISTRY

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

    def _pick(summary: dict) -> dict:
        out = {}
        for k in COMPARE_KEYS:
            v = summary.get(k, 0.0)
            try:
                out[k] = float(v)
            except Exception:
                out[k] = None
        return out

    rows = []
    for rid in ids:
        r = REGISTRY.get(rid)
        if not r:
            raise HTTPException(status_code=404, detail=f"run not found: {rid}")
        rows.append({"run_id": rid, **_pick(r.get("summary", {}))})
    diffs = []
    base = rows[0]
    for other in rows[1:]:
        for k in COMPARE_KEYS:
            b = base.get(k) or 0.0
            t = other.get(k) or 0.0
            d = t - b
            pct = (d / b * 100.0) if b else None
            hit = None
            if threshold is not None and pct is not None:
                hit = abs(pct) >= threshold
            diffs.append(
                {
                    "base": base["run_id"],
                    "target": other["run_id"],
                    "metric": k,
                    "abs": d,
                    "pct": pct,
                    "hit": hit,
                }
            )
    buf = io.StringIO()
    # meta lines
    import datetime as _dt

    buf.write(f"# generated_at: {_dt.datetime.utcnow().isoformat()}Z\n")
    buf.write(f"# base_id: {base['run_id']}\n")
    if threshold is not None:
        buf.write(f"# threshold_pct: {threshold}\n")
    w = csv.DictWriter(
        buf, fieldnames=["base", "target", "metric", "abs", "pct", "hit"]
    )
    w.writeheader()
    for r in diffs:
        w.writerow(r)
    headers = {"Content-Disposition": "attachment; filename=compare_diffs.csv"}
    from fastapi import Response

    return Response(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers
    )
