from app.api import app
from fastapi import Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List
from pathlib import Path
import csv
import io

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

    # keys filter
    use_keys = COMPARE_KEYS
    if keys:
        req = [x.strip() for x in keys.split(",") if x.strip()]
        filt = [k for k in req if k in COMPARE_KEYS]
        if filt:
            use_keys = filt

    rows = []
    for rid in ids:
        rec = REGISTRY.get(rid)
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
