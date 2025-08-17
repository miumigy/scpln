from app.api import app
from fastapi import Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.post("/ui/compare", response_class=HTMLResponse)
def ui_compare(request: Request, run_ids: str = Form(...)):
    ids: List[str] = [x.strip() for x in run_ids.split(",") if x.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Need 2 or more run_ids")

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

    diffs = []
    if len(rows) >= 2:
        base = rows[0]
        for other in rows[1:]:
            diff = {"base": base["run_id"], "target": other["run_id"]}
            for k in COMPARE_KEYS:
                b = base.get(k) or 0.0
                t = other.get(k) or 0.0
                d = t - b
                pct = (d / b * 100.0) if b else None
                diff[k] = {"abs": d, "pct": pct}
            diffs.append(diff)

    return templates.TemplateResponse(
        "compare.html",
        {"request": request, "rows": rows, "diffs": diffs, "keys": COMPARE_KEYS},
    )
