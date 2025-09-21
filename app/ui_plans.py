from __future__ import annotations

from app.api import app
import logging
import json
from fastapi.responses import HTMLResponse
from fastapi import Request, Form
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app import db
from app import plans_api as _plans_api  # for reuse handlers
from app import runs_api as _runs_api  # for Plan & Run adapter
from app.metrics import PLANS_CREATED, PLANS_RECONCILED, PLANS_VIEWED
from app.utils import ms_to_jst_str


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
        cutover_date = (
            p.get("cutover_date")
            or cut.get("cutover_date")
            or cut_adj.get("cutover_date")
        )
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
        policy = (
            cut.get("anchor_policy")
            or cut_adj.get("anchor_policy")
            or bs.get("anchor_policy")
            or bs_adj.get("anchor_policy")
        )

        rows.append(
            {
                **p,
                "cutover_date": cutover_date,
                "recon_window_days": recon_window_days,
                "recon_summary": summary,
                "policy": policy,
            }
        )
    return templates.TemplateResponse(
        request,
        "plans.html",
        {
            "subtitle": "Plan Versions",
            "plans": rows,
        },
    )


@app.get("/ui/plans/{version_id}", response_class=HTMLResponse)
def ui_plan_detail(version_id: str, request: Request):
    ver = db.get_plan_version(version_id)
    if not ver:
        return templates.TemplateResponse(
            request,
            "plans_detail.html",
            {
                "subtitle": "プラン詳細",
                "error": "version not found",
            },
        )
    recon = db.get_plan_artifact(version_id, "reconciliation_log.json") or {}
    recon_adj = (
        db.get_plan_artifact(version_id, "reconciliation_log_adjusted.json") or {}
    )
    plan_final = db.get_plan_artifact(version_id, "plan_final.json") or {}
    plan_mrp = db.get_plan_artifact(version_id, "mrp.json") or {}
    source_meta = db.get_plan_artifact(version_id, "source.json") or {}
    plan_state = db.get_plan_artifact(version_id, "state.json") or {
        "state": "draft",
        "invalid": [],
    }
    aggregate = db.get_plan_artifact(version_id, "aggregate.json") or {}
    sku_week = db.get_plan_artifact(version_id, "sku_week.json") or {}
    disagg_rows_sample = []
    try:
        disagg_rows_sample = list((sku_week.get("rows") or [])[:200])
    except Exception:
        disagg_rows_sample = []
    # schedule rows from mrp.json (first 200)
    schedule_rows_sample = []
    schedule_total = 0
    try:
        mrows = list((plan_mrp.get("rows") or []))
        schedule_total = len(mrows)
        schedule_rows_sample = mrows[:200]
    except Exception:
        schedule_rows_sample = []
        schedule_total = 0

    config_version_id = ver.get("config_version_id")
    canonical_snapshot = (
        db.get_plan_artifact(version_id, "canonical_snapshot.json") or {}
    )
    canonical_meta = (
        canonical_snapshot.get("meta")
        if isinstance(canonical_snapshot, dict)
        else {}
    )
    if hasattr(canonical_meta, "model_dump"):
        canonical_meta = canonical_meta.model_dump()
    canonical_counts: dict[str, int] = {}
    if isinstance(canonical_snapshot, dict):
        for key in (
            "items",
            "nodes",
            "arcs",
            "bom",
            "demands",
            "capacities",
            "calendars",
            "hierarchies",
        ):
            val = canonical_snapshot.get(key)
            if isinstance(val, list):
                canonical_counts[key] = len(val)

    planning_inputs = db.get_plan_artifact(version_id, "planning_inputs.json") or {}
    planning_summary = {}
    if isinstance(planning_inputs, dict):
        def _len(key: str) -> int:
            val = planning_inputs.get(key)
            return len(val) if isinstance(val, list) else 0

        planning_summary = {
            "schema_version": planning_inputs.get("schema_version"),
            "demand_family": _len("demand_family"),
            "capacity": _len("capacity"),
            "mix_share": _len("mix_share"),
            "item_master": _len("item_master"),
            "inventory": _len("inventory"),
            "open_po": _len("open_po"),
        }

    # Validate summary (MVP)
    validate = {}
    try:
        # 1) tolerance violations from reconciliation summary (before/after)
        tol_before = (recon.get("summary") or {}).get("tol_violations")
        tol_after = (recon_adj.get("summary") or {}).get("tol_violations")
        # 2) negative inventory counts from mrp rows
        mrows = list((plan_mrp.get("rows") or []))
        neg_inv = 0
        frac_sched = 0
        for r in mrows:
            try:
                ohs = float(r.get("on_hand_start") or 0)
                ohe = float(r.get("on_hand_end") or 0)
                if ohe < 0 or ohs < 0:
                    neg_inv += 1
                sr = float(r.get("scheduled_receipts") or 0)
                if abs(sr - round(sr)) > 1e-6:
                    frac_sched += 1
            except Exception:
                pass
        # 3) capacity violations from weekly_summary (adjusted_load > capacity)
        ws = plan_final.get("weekly_summary") or []
        cap_over = 0
        for r in ws:
            try:
                cap = float(r.get("capacity") or 0)
                adj = float(r.get("adjusted_load") or 0)
                if adj - cap > 1e-6:
                    cap_over += 1
            except Exception:
                pass
        validate = {
            "tol_violations_before": tol_before,
            "tol_violations_after": tol_after,
            "neg_inventory_rows": neg_inv,
            "fractional_receipts_rows": frac_sched,
            "capacity_over_weeks": cap_over,
            "mrp_total_rows": len(mrows),
            "weekly_total_rows": len(ws),
        }
    except Exception:
        validate = {}
    # truncate deltas for display
    deltas = list((recon.get("deltas") or [])[:50]) if recon else []
    deltas_adj = list((recon_adj.get("deltas") or [])[:50]) if recon_adj else []
    # latest runs for this plan's base scenario (if available)
    latest_runs: list[dict] = []
    latest_ids: list[str] = []
    base_sid = (ver or {}).get("base_scenario_id")
    related_plans: list[dict] = []
    config_runs: list[dict] = []
    if base_sid is not None:
        try:
            from app.run_registry import REGISTRY  # type: ignore

            rows = []
            if hasattr(REGISTRY, "list_page"):
                try:
                    resp = REGISTRY.list_page(
                        offset=0,
                        limit=5,
                        sort="started_at",
                        order="desc",
                        schema_version=None,
                        config_id=None,
                        scenario_id=int(base_sid),
                        detail=False,
                    )
                    rows = resp.get("runs") or []
                except Exception:
                    rows = []
            if not rows and hasattr(REGISTRY, "list_ids"):
                try:
                    ids = REGISTRY.list_ids()
                    for rid in ids:
                        rec = REGISTRY.get(rid) or {}
                        if rec.get("scenario_id") == base_sid:
                            rows.append(rec)
                            if len(rows) >= 5:
                                break
                except Exception:
                    rows = []
            for r in rows:
                rid = r.get("run_id")
                if not rid:
                    continue
                latest_ids.append(rid)
                latest_runs.append(
                    {
                        "run_id": rid,
                        "started_at": r.get("started_at"),
                        "duration_ms": r.get("duration_ms"),
                        "fill_rate": (r.get("summary") or {}).get("fill_rate"),
                        "profit_total": (r.get("summary") or {}).get("profit_total"),
                    }
                )
        except Exception:
            latest_runs = []
            latest_ids = []
        # 関連Plan（同一base_scenarioの最新）
        try:
            related = db.list_plan_versions_by_base(int(base_sid), limit=5)
            # 自分自身を除外
            related_plans = [p for p in related if p.get("version_id") != version_id]
        except Exception:
            related_plans = []
    if config_version_id is not None:
        try:
            from app.run_registry import REGISTRY  # type: ignore

            run_rows = []
            if hasattr(REGISTRY, "list_page"):
                try:
                    resp = REGISTRY.list_page(
                        offset=0,
                        limit=200,
                        sort="started_at",
                        order="desc",
                        schema_version=None,
                        config_id=None,
                        scenario_id=None,
                        detail=True,
                    )
                    run_rows = resp.get("runs") or []
                except Exception:
                    run_rows = []
            if not run_rows:
                run_rows = REGISTRY.list()
            for r in run_rows:
                if r.get("config_version_id") == config_version_id:
                    config_runs.append(
                        {
                            "run_id": r.get("run_id"),
                            "started_at": r.get("started_at"),
                            "started_at_str": ms_to_jst_str(r.get("started_at")),
                            "scenario_id": r.get("scenario_id"),
                            "summary": r.get("summary") or {},
                        }
                    )
            config_runs = config_runs[:10]
        except Exception:
            config_runs = []
    # KPI preview (MVP): capacity/utilization and spill totals
    kpi_preview = {}
    try:
        ws = plan_final.get("weekly_summary") or []
        cap_total = sum(float(r.get("capacity") or 0) for r in ws)
        adj_total = sum(float(r.get("adjusted_load") or 0) for r in ws)
        spill_in_total = sum(float(r.get("spill_in") or 0) for r in ws)
        spill_out_total = sum(float(r.get("spill_out") or 0) for r in ws)
        util = (adj_total / cap_total * 100.0) if cap_total else None
        # DET集計（需要/供給/バックログ）から SL と発注合計を推定
        det_dem = det_sup = det_bkl = 0.0
        try:
            for row in recon.get("deltas") or []:
                det_dem += float(row.get("det_demand") or 0)
                det_sup += float(row.get("det_supply") or 0)
                det_bkl += float(row.get("det_backlog") or 0)
        except Exception:
            det_dem = det_sup = det_bkl = 0.0
        sl = ((det_dem - det_bkl) / det_dem * 100.0) if det_dem else None
        # 在庫（MVP）: MRPの最初の週の on_hand_start 合計を在庫初期合計として表示
        inv_init_total = None
        try:
            mrows = list(plan_mrp.get("rows") or [])
            if mrows:
                weeks = []
                for r in mrows:
                    w = str(r.get("week"))
                    if w and w not in weeks:
                        weeks.append(w)
                firstw = weeks[0] if weeks else None
                if firstw:
                    inv_init_total = sum(
                        float(r.get("on_hand_start") or 0)
                        for r in mrows
                        if str(r.get("week")) == firstw
                    )
        except Exception:
            inv_init_total = None
        kpi_preview = {
            "capacity_total": cap_total,
            "adjusted_total": adj_total,
            "util_pct": util,
            "spill_in_total": spill_in_total,
            "spill_out_total": spill_out_total,
            "det_demand_total": det_dem,
            "det_supply_total": det_sup,
            "det_backlog_total": det_bkl,
            "sl_pct": sl,
            "inv_initial_total": inv_init_total,
            "viol_before": (recon.get("summary") or {}).get("tol_violations"),
            "viol_after": (recon_adj.get("summary") or {}).get("tol_violations"),
            "window_days": (plan_final.get("boundary_summary") or {}).get(
                "window_days"
            ),
            "anchor_policy": (plan_final.get("boundary_summary") or {}).get(
                "anchor_policy"
            ),
        }
    except Exception:
        kpi_preview = {}
    # 計測イベント: plan_results_viewed（詳細表示）
    try:
        logging.info(
            "plan_results_viewed",
            extra={
                "event": "plan_results_viewed",
                "version_id": version_id,
                "base_scenario_id": (ver or {}).get("base_scenario_id"),
            },
        )
        try:
            PLANS_VIEWED.inc()
        except Exception:
            pass
    except Exception:
        pass
    return templates.TemplateResponse(
        request,
        "plans_detail.html",
        {
            "subtitle": f"プラン詳細 {version_id}",
            "version_id": version_id,
            "version": ver,
            "created_from_run_id": (source_meta or {}).get("source_run_id"),
            "recon": recon,
            "recon_adj": recon_adj,
            "weekly_summary": plan_final.get("weekly_summary"),
            "boundary_summary": plan_final.get("boundary_summary"),
            "deltas": deltas,
            "deltas_adj": deltas_adj,
            "kpi_preview": kpi_preview,
            "latest_runs": latest_runs,
            "latest_run_ids": latest_ids,
            "related_plans": related_plans,
            "aggregate": aggregate,
            "disagg_rows": disagg_rows_sample,
            "disagg_total": (
                len((sku_week.get("rows") or [])) if isinstance(sku_week, dict) else 0
            ),
            "schedule_rows": schedule_rows_sample,
            "schedule_total": schedule_total,
            "validate": validate,
            "plan_state": plan_state,
            "config_version_id": config_version_id,
            "canonical_meta": canonical_meta,
            "canonical_counts": canonical_counts,
            "planning_summary": planning_summary,
            "config_runs": config_runs,
        },
    )


@app.post("/ui/plans/{version_id}/reconcile")
def ui_plan_reconcile(
    version_id: str,
    request: Request,
    # フォーム入力（空文字はNoneとして扱う）
    cutover_date: str | None = Form(""),
    recon_window_days: str | None = Form(""),
    anchor_policy: str | None = Form(""),
    tol_abs: str | None = Form(""),
    tol_rel: str | None = Form(""),
    calendar_mode: str | None = Form(""),
    carryover: str | None = Form(""),
    carryover_split: str | None = Form(""),
    input_dir: str = Form("samples/planning"),
    apply_adjusted: int | None = Form(default=None),
    weeks: int = Form(4),
    lt_unit: str = Form("day"),
):
    # 空文字はNoneへ正規化
    def _nz(v: str | None):
        return None if (v is None or v == "") else v

    body = {
        "cutover_date": _nz(cutover_date),
        "recon_window_days": _nz(recon_window_days),
        "anchor_policy": _nz(anchor_policy),
        "tol_abs": _nz(tol_abs),
        "tol_rel": _nz(tol_rel),
        "calendar_mode": _nz(calendar_mode),
        "carryover": _nz(carryover),
        "carryover_split": _nz(carryover_split),
        "input_dir": input_dir,
        "apply_adjusted": bool(apply_adjusted),
        "weeks": weeks,
        "lt_unit": lt_unit,
    }
    try:
        _plans_api.post_plan_reconcile(version_id, body)  # reuse handler
        # 実行ステートを自動前進（MVP）
        try:
            state = db.get_plan_artifact(version_id, "state.json") or {
                "state": "draft",
                "invalid": [],
            }
            state["state"] = "executed"
            inv = set(state.get("invalid") or [])
            # executed までの無効フラグをクリア
            for s in ["draft", "aggregated", "disaggregated", "scheduled", "executed"]:
                inv.discard(s)
                if s == "executed":
                    break
            state["invalid"] = sorted(list(inv))
            db.upsert_plan_artifact(
                version_id, "state.json", json.dumps(state, ensure_ascii=False)
            )
            try:
                db.update_plan_version(version_id, status="executed")
            except Exception:
                pass
        except Exception:
            pass
        try:
            logging.info(
                "plan_executed",
                extra={
                    "event": "plan_executed",
                    "version_id": version_id,
                    "apply_adjusted": bool(apply_adjusted),
                    "weeks": weeks,
                    "lt_unit": lt_unit,
                },
            )
            try:
                PLANS_RECONCILED.inc()
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        pass
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


@app.post("/ui/plans/{version_id}/plan_run_auto")
def ui_plan_run_auto(
    version_id: str,
    request: Request,
    input_dir: str = Form("samples/planning"),
    weeks: int = Form(4),
    lt_unit: str = Form("day"),
    cutover_date: str | None = Form(""),
    recon_window_days: str | None = Form(""),
    anchor_policy: str | None = Form(""),
    tol_abs: str | None = Form(""),
    tol_rel: str | None = Form(""),
    calendar_mode: str | None = Form(""),
    carryover: str | None = Form(""),
    carryover_split: str | None = Form(""),
    apply_adjusted: int | None = Form(default=None),
    queue_job: int | None = Form(default=None),
):
    """Plan & Run（自動補完）: 既存Planの情報を可能な範囲で引き継ぎ、/runs を呼び出して新規Planを生成。
    - queue_job チェック時は非同期（ジョブ投入）。
    - それ以外は同期で新規Plan作成し詳細にリダイレクト。
    """
    ver = db.get_plan_version(version_id) or {}
    # 既存のcutover/window/policyを引き継ぎ（存在する場合）
    # plan_final.boundary_summary にもフォールバック
    plan_final = db.get_plan_artifact(version_id, "plan_final.json") or {}
    bs = (
        (plan_final.get("boundary_summary") or {})
        if isinstance(plan_final, dict)
        else {}
    )
    cutover_date = ver.get("cutover_date") or bs.get("cutover_date")
    recon_window_days = ver.get("recon_window_days") or bs.get("window_days")
    anchor_policy = bs.get("anchor_policy")
    body = {
        "pipeline": "integrated",
        "async": bool(queue_job),
        "options": {
            "input_dir": input_dir,
            "weeks": weeks,
            "lt_unit": lt_unit,
            "cutover_date": cutover_date,
            "recon_window_days": recon_window_days,
            "anchor_policy": anchor_policy,
            "tol_abs": tol_abs,
            "tol_rel": tol_rel,
            "calendar_mode": calendar_mode,
            "carryover": carryover,
            "carryover_split": carryover_split,
            "apply_adjusted": bool(apply_adjusted),
        },
    }
    res = _runs_api.post_runs(body)
    from fastapi.responses import RedirectResponse

    # 正常系でlocationへ誘導
    if isinstance(res, dict) and res.get("location"):
        return RedirectResponse(url=str(res.get("location")), status_code=303)
    # 失敗時は元画面へ
    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


_STEPS = ["draft", "aggregated", "disaggregated", "scheduled", "executed"]


@app.post("/ui/plans/{version_id}/state/advance")
def ui_plan_state_advance(version_id: str, request: Request, to: str = Form(...)):
    if to not in _STEPS:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)
    state = db.get_plan_artifact(version_id, "state.json") or {
        "state": "draft",
        "invalid": [],
    }
    curr = state.get("state") or "draft"
    if _STEPS.index(to) < _STEPS.index(curr):
        to = curr
    state["state"] = to
    inv = set(state.get("invalid") or [])
    for s in _STEPS:
        if _STEPS.index(s) <= _STEPS.index(to):
            inv.discard(s)
    state["invalid"] = sorted(list(inv))
    db.upsert_plan_artifact(
        version_id, "state.json", json.dumps(state, ensure_ascii=False)
    )
    try:
        db.update_plan_version(version_id, status=to)
    except Exception:
        pass
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


@app.post("/ui/plans/{version_id}/state/invalidate")
def ui_plan_state_invalidate(
    version_id: str, request: Request, from_step: str = Form(...)
):
    if from_step not in _STEPS:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)
    idx = _STEPS.index(from_step)
    state = {
        "state": from_step,
        "invalid": _STEPS[idx + 1 :],
    }
    db.upsert_plan_artifact(
        version_id, "state.json", json.dumps(state, ensure_ascii=False)
    )
    try:
        db.update_plan_version(version_id, status=from_step)
    except Exception:
        pass
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


@app.post("/ui/plans/run")
def ui_plans_run(
    request: Request,
    input_dir: str = Form("samples/planning"),
    weeks: int = Form(4),
    lt_unit: str = Form("day"),
    cutover_date: str | None = Form(""),
    recon_window_days: str | None = Form(""),
    anchor_policy: str | None = Form(""),
    tol_abs: str | None = Form(""),
    tol_rel: str | None = Form(""),
    calendar_mode: str | None = Form(""),
    carryover: str | None = Form(""),
    carryover_split: str | None = Form(""),
    apply_adjusted: int | None = Form(default=None),
):
    body = {
        "input_dir": input_dir,
        "weeks": weeks,
        "lt_unit": lt_unit,
        "cutover_date": cutover_date,
        "recon_window_days": recon_window_days,
        "anchor_policy": anchor_policy,
        "tol_abs": tol_abs,
        "tol_rel": tol_rel,
        "calendar_mode": calendar_mode,
        "carryover": carryover,
        "carryover_split": carryover_split,
        "apply_adjusted": bool(apply_adjusted),
    }
    res = _plans_api.post_plans_integrated_run(body)
    version_id = res.get("version_id")
    # 計測イベント: plan_created（新規作成）
    try:
        logging.info(
            "plan_created",
            extra={
                "event": "plan_created",
                "version_id": version_id,
                "input_dir": input_dir,
                "weeks": weeks,
                "lt_unit": lt_unit,
                "anchor_policy": anchor_policy,
            },
        )
        try:
            PLANS_CREATED.inc()
        except Exception:
            pass
    except Exception:
        pass
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)
