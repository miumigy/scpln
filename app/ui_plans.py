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
from core.config.storage import list_canonical_version_summaries


_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


def _form_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"", "0", "false", "off", "no"}:
        return False
    return text in {"1", "true", "on", "yes", "y"}


def _canonical_version_options(limit: int = 50):
    try:
        summaries = list_canonical_version_summaries(limit=limit)
    except Exception:
        return []

    options = []
    for summary in summaries:
        meta = summary.meta
        if meta.version_id is None:
            continue
        label_parts = [str(meta.version_id)]
        if meta.name:
            label_parts.append(meta.name)
        if meta.status:
            label_parts.append(f"[{meta.status}]")
        label = " ".join(label_parts)
        options.append(
            {
                "id": meta.version_id,
                "label": label,
                "name": meta.name,
                "status": meta.status,
            }
        )
    return options


def _scenario_options(limit: int = 200):
    try:
        db.init_db()
        rows = db.list_scenarios(limit=limit)
    except Exception:
        logging.exception("ui_plans_list_scenarios_failed")
        return []

    options = []
    for row in rows:
        sid = row.get("id")
        if sid is None:
            continue
        label_parts = [str(sid)]
        name = row.get("name")
        if name:
            label_parts.append(name)
        tag = row.get("tag")
        if tag:
            label_parts.append(f"[{tag}]")
        label = " ".join(label_parts)
        options.append(
            {
                "id": sid,
                "label": label,
                "name": name,
                "tag": tag,
                "locked": bool(row.get("locked")),
            }
        )
    return options


def _fetch_plan_rows(limit: int = 200):
    plans = db.list_plan_versions(limit=limit)
    rows = []
    for p in plans:
        ver = p.get("version_id")
        recon = db.get_plan_artifact(ver, "reconciliation_log.json") or {}
        summary = (recon or {}).get("summary") or {}
        cut = (recon or {}).get("cutover") or {}
        recon_adj = db.get_plan_artifact(ver, "reconciliation_log_adjusted.json") or {}
        cut_adj = (recon_adj or {}).get("cutover") or {}
        plan_final = db.get_plan_artifact(ver, "plan_final.json") or {}
        plan_final_adj = db.get_plan_artifact(ver, "plan_final_adjusted.json") or {}
        bs = (plan_final or {}).get("boundary_summary") or {}
        bs_adj = (plan_final_adj or {}).get("boundary_summary") or {}

        cutover_date = (
            p.get("cutover_date")
            or cut.get("cutover_date")
            or cut_adj.get("cutover_date")
        )
        recon_window_days = p.get("recon_window_days")
        if recon_window_days is None:
            recon_window_days = cut.get("recon_window_days")
        if recon_window_days is None:
            recon_window_days = cut_adj.get("recon_window_days")
        if recon_window_days is None:
            recon_window_days = bs.get("window_days")
        if recon_window_days is None:
            recon_window_days = bs_adj.get("window_days")
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
    return rows


def _render_plans_page(
    request: Request,
    *,
    plans,
    error: str | None = None,
    form_defaults: dict | None = None,
):
    canonical_options = _canonical_version_options()
    scenario_options = _scenario_options()
    return templates.TemplateResponse(
        request,
        "plans.html",
        {
            "subtitle": "Plan Versions",
            "plans": plans,
            "error": error,
            "form_defaults": form_defaults or {},
            "canonical_options": canonical_options,
            "scenario_options": scenario_options,
        },
    )


@app.get("/ui/plans", response_class=HTMLResponse)
def ui_plans(request: Request):
    rows = _fetch_plan_rows()
    return _render_plans_page(request, plans=rows)


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
        canonical_snapshot.get("meta") if isinstance(canonical_snapshot, dict) else {}
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
    # RunRegistry から Plan/Config/Scenario 関連 Run を取得
    base_sid = (ver or {}).get("base_scenario_id")
    base_sid_str = str(base_sid) if base_sid is not None else None
    latest_runs: list[dict] = []
    latest_ids: list[str] = []
    related_plans: list[dict] = []
    config_runs: list[dict] = []
    plan_runs: list[dict] = []
    plan_run_ids: list[str] = []

    run_rows_all: list[dict] = []
    try:
        from app.run_registry import REGISTRY  # type: ignore

        if hasattr(REGISTRY, "list_page"):
            try:
                resp = REGISTRY.list_page(
                    offset=0,
                    limit=500,
                    sort="started_at",
                    order="desc",
                    schema_version=None,
                    config_id=None,
                    scenario_id=None,
                    detail=True,
                )
                run_rows_all = resp.get("runs") or []
            except Exception:
                run_rows_all = []
        if not run_rows_all and hasattr(REGISTRY, "list"):
            try:
                run_rows_all = REGISTRY.list()
            except Exception:
                run_rows_all = []
    except Exception:
        run_rows_all = []

    for r in run_rows_all:
        rid = r.get("run_id")
        if not rid:
            continue
        summary_obj = r.get("summary") or {}
        started_at = r.get("started_at")
        formatted = {
            "run_id": rid,
            "started_at": started_at,
            "started_at_str": ms_to_jst_str(started_at),
            "duration_ms": r.get("duration_ms"),
            "fill_rate": summary_obj.get("fill_rate"),
            "profit_total": summary_obj.get("profit_total"),
            "scenario_id": r.get("scenario_id"),
        }
        scenario_val = r.get("scenario_id")
        if (
            base_sid_str is not None
            and scenario_val is not None
            and str(scenario_val) == base_sid_str
            and len(latest_runs) < 5
        ):
            latest_runs.append(formatted)
            latest_ids.append(rid)
        plan_val = r.get("plan_version_id")
        if (
            plan_val is not None
            and str(plan_val) == str(version_id)
            and len(plan_runs) < 10
        ):
            plan_runs.append(formatted)
            plan_run_ids.append(rid)
        if (
            config_version_id is not None
            and r.get("config_version_id") == config_version_id
            and len(config_runs) < 10
        ):
            config_runs.append(formatted)

    # 関連Plan（同一base_scenarioの最新）
    if base_sid is not None:
        try:
            related = db.list_plan_versions_by_base(int(base_sid), limit=5)
            related_plans = [p for p in related if p.get("version_id") != version_id]
        except Exception:
            related_plans = []
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
            "plan_runs": plan_runs,
            "plan_run_ids": plan_run_ids,
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
    apply_adjusted: str | None = Form(default=None),
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
        "apply_adjusted": _form_bool(apply_adjusted),
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
                    "apply_adjusted": _form_bool(apply_adjusted),
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
    apply_adjusted: str | None = Form(default=None),
    queue_job: str | None = Form(default=None),
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
    config_version_id = ver.get("config_version_id")
    if config_version_id is None:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(
            url=f"/ui/plans/{version_id}?error=no_config_version",
            status_code=303,
        )
    source_meta = db.get_plan_artifact(version_id, "source.json") or {}
    body = {
        "pipeline": "integrated",
        "async": _form_bool(queue_job),
        "options": {
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
            "apply_adjusted": _form_bool(apply_adjusted),
            "config_version_id": config_version_id,
            "base_scenario_id": ver.get("base_scenario_id"),
            "source_run_id": source_meta.get("source_run_id"),
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
    apply_adjusted: str | None = Form(default=None),
    config_version_id: str | None = Form(""),
    base_scenario_id: str | None = Form(""),
):
    base_scenario_raw = (base_scenario_id or "").strip()
    try:
        base_scenario_int = int(base_scenario_raw) if base_scenario_raw else None
    except ValueError:
        base_scenario_int = None

    form_defaults = {
        "config_version_id": config_version_id or "",
        "weeks": weeks,
        "lt_unit": lt_unit,
        "cutover_date": cutover_date or "",
        "recon_window_days": recon_window_days or "",
        "anchor_policy": anchor_policy or "",
        "tol_abs": tol_abs or "",
        "tol_rel": tol_rel or "",
        "calendar_mode": calendar_mode or "",
        "carryover": carryover or "",
        "carryover_split": carryover_split or "",
        "apply_adjusted": "1" if _form_bool(apply_adjusted) else "",
        "base_scenario_id": base_scenario_raw,
    }
    if not (config_version_id or "").strip():
        rows = _fetch_plan_rows()
        return _render_plans_page(
            request,
            plans=rows,
            error="Canonical設定バージョンを選択してください。",
            form_defaults=form_defaults,
        )

    body = {
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
        "apply_adjusted": _form_bool(apply_adjusted),
        "config_version_id": config_version_id,
        "base_scenario_id": base_scenario_int,
    }
    res = _plans_api.post_plans_integrated_run(body)
    if hasattr(res, "status_code") and res.status_code >= 400:
        error_message = "Plan作成に失敗しました。"
        try:
            payload = json.loads(res.body)
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if isinstance(detail, str) and detail:
                error_message = detail
            elif isinstance(detail, dict):
                error_message = detail.get("message") or json.dumps(
                    detail, ensure_ascii=False
                )
            elif isinstance(detail, list):
                error_message = "; ".join(str(item) for item in detail if item)
        except Exception:
            pass
        rows = _fetch_plan_rows()
        return _render_plans_page(
            request,
            plans=rows,
            error=error_message,
            form_defaults=form_defaults,
        )
    version_id = res.get("version_id")
    # 計測イベント: plan_created（新規作成）
    try:
        logging.info(
            "plan_created",
            extra={
                "event": "plan_created",
                "version_id": version_id,
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
