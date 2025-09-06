from __future__ import annotations

from app.api import app
from fastapi.responses import HTMLResponse
from fastapi import Request
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import db
from app import plans_api as _plans_api  # for reuse handlers


_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


@app.get("/ui/plans", response_class=HTMLResponse)
def ui_plans(request: Request):
    plans = db.list_plan_versions(limit=200)
    # enrich with summary if exists (lightweight; avoid N+1 heavy loads)
    rows = []
    for p in plans:
        ver = p.get("version_id")
        # 1) base reconciliation
        recon = db.get_plan_artifact(ver, "reconciliation_log.json") or {}
        summary = (recon or {}).get("summary") or {}
        cut = (recon or {}).get("cutover") or {}
        # 2) adjusted reconciliation (fallback)
        recon_adj = db.get_plan_artifact(ver, "reconciliation_log_adjusted.json") or {}
        cut_adj = (recon_adj or {}).get("cutover") or {}
        # 3) boundary summary (policy/window fallback)
        plan_final = db.get_plan_artifact(ver, "plan_final.json") or {}
        plan_final_adj = db.get_plan_artifact(ver, "plan_final_adjusted.json") or {}
        bs = (plan_final or {}).get("boundary_summary") or {}
        bs_adj = (plan_final_adj or {}).get("boundary_summary") or {}

        # 補完: cutover_date は cutover からのみ（boundaryはperiodのため未採用）
        cutover_date = p.get("cutover_date") or cut.get("cutover_date") or cut_adj.get("cutover_date")
        # 補完: window は cutover.recon_window_days → adjusted → boundary_summary.window_days
        recon_window_days = p.get("recon_window_days")
        if recon_window_days is None:
            recon_window_days = cut.get("recon_window_days")
        if recon_window_days is None:
            recon_window_days = cut_adj.get("recon_window_days")
        if recon_window_days is None:
            recon_window_days = bs.get("window_days")
        if recon_window_days is None:
            recon_window_days = bs_adj.get("window_days")
        # 補完: policy は cutover.anchor_policy → adjusted → boundary_summary.anchor_policy
        policy = cut.get("anchor_policy") or cut_adj.get("anchor_policy") or bs.get("anchor_policy") or bs_adj.get("anchor_policy")

        rows.append({
            **p,
            "cutover_date": cutover_date,
            "recon_window_days": recon_window_days,
            "recon_summary": summary,
            "policy": policy,
        })
    return templates.TemplateResponse(
        "plans.html",
        {
            "request": request,
            "subtitle": "プランバージョン一覧",
            "plans": rows,
        },
    )


@app.get("/ui/plans/{version_id}", response_class=HTMLResponse)
def ui_plan_detail(version_id: str, request: Request):
    ver = db.get_plan_version(version_id)
    if not ver:
        return templates.TemplateResponse(
            "plans_detail.html",
            {
                "request": request,
                "subtitle": "プラン詳細",
                "error": "version not found",
            },
        )
    recon = db.get_plan_artifact(version_id, "reconciliation_log.json") or {}
    recon_adj = (
        db.get_plan_artifact(version_id, "reconciliation_log_adjusted.json") or {}
    )
    plan_final = db.get_plan_artifact(version_id, "plan_final.json") or {}
    # truncate deltas for display
    deltas = list((recon.get("deltas") or [])[:50]) if recon else []
    deltas_adj = list((recon_adj.get("deltas") or [])[:50]) if recon_adj else []
    return templates.TemplateResponse(
        "plans_detail.html",
        {
            "request": request,
            "subtitle": f"プラン詳細 {version_id}",
            "version_id": version_id,
            "version": ver,
            "recon": recon,
            "recon_adj": recon_adj,
            "weekly_summary": plan_final.get("weekly_summary"),
            "boundary_summary": plan_final.get("boundary_summary"),
            "deltas": deltas,
            "deltas_adj": deltas_adj,
        },
    )


@app.post("/ui/plans/{version_id}/reconcile")
def ui_plan_reconcile(
    version_id: str,
    request,
    cutover_date: str | None = None,
    recon_window_days: int | None = None,
    anchor_policy: str | None = None,
    tol_abs: float | None = None,
    tol_rel: float | None = None,
    calendar_mode: str | None = None,
    carryover: str | None = None,
    carryover_split: float | None = None,
    input_dir: str | None = "samples/planning",
    apply_adjusted: int | None = None,
    weeks: int | None = 4,
    lt_unit: str | None = "day",
):
    body = {
        "cutover_date": cutover_date,
        "recon_window_days": recon_window_days,
        "anchor_policy": anchor_policy,
        "tol_abs": tol_abs,
        "tol_rel": tol_rel,
        "calendar_mode": calendar_mode,
        "carryover": carryover,
        "carryover_split": carryover_split,
        "input_dir": input_dir,
        "apply_adjusted": bool(apply_adjusted),
        "weeks": weeks,
        "lt_unit": lt_unit,
    }
    try:
        _plans_api.post_plan_reconcile(version_id, body)  # reuse handler
    except Exception:
        pass
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)
