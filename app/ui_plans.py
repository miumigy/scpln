from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import logging
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app import db
from app.metrics import (
    PLAN_DB_CAPACITY_TRIM_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    PLAN_DB_LAST_TRIM_TIMESTAMP,
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLANS_CREATED,
    PLANS_RECONCILED,
    PLANS_VIEWED,
)
from app.utils import ms_to_jst_str
from core.config.storage import (
    CanonicalConfigNotFoundError,
    get_canonical_config,
    list_canonical_version_summaries,
)
from core.config import build_planning_inputs
from core.plan_repository import PlanRepository
from core.plan_repository_views import (
    fetch_aggregate_rows as repo_fetch_aggregate_rows,
    fetch_detail_rows as repo_fetch_detail_rows,
    fetch_override_events as repo_fetch_override_events,
    latest_state_from_events,
    summarize_audit_events,
)


router = APIRouter()


_BASE_DIR = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _get_plans_api():
    from app import plans_api

    return plans_api


@lru_cache(maxsize=1)
def _get_runs_api():
    from app import runs_api

    return runs_api


def get_plan_repository() -> PlanRepository:
    return PlanRepository(
        db._conn,
        PLAN_DB_WRITE_LATENCY,
        PLAN_SERIES_ROWS_TOTAL,
        PLAN_DB_LAST_SUCCESS_TIMESTAMP,
        PLAN_DB_CAPACITY_TRIM_TOTAL,
        PLAN_DB_LAST_TRIM_TIMESTAMP,
    )


print("DEBUG: Initializing Jinja2Templates")
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
    except Exception as e:
        logging.exception(f"ui_plans_canonical_version_options_failed: {e}")
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
    except Exception as e:
        logging.exception(f"ui_plans_list_scenarios_failed: {e}")
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


def _normalize_plan_state(raw: dict | None) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    state = dict(raw)
    status = state.get("status") or state.get("state")
    if status is None:
        status = "draft"
    state["status"] = status
    state.setdefault("state", status)
    state.setdefault("display_status", str(status))
    timestamp = (
        state.get("approved_at")
        or state.get("submitted_at")
        or state.get("timestamp")
    )
    if state.get("display_time") is None and timestamp is not None:
        try:
            ts_int = int(timestamp)
            dt = datetime.fromtimestamp(ts_int / 1000, tz=timezone.utc)
            state["display_time"] = dt.isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    invalid = state.get("invalid")
    if invalid is None:
        state["invalid"] = []
    elif not isinstance(invalid, list):
        state["invalid"] = [invalid]
    state.setdefault("source", "unknown")
    return state


def _fetch_plan_rows(limit: int = 50, offset: int = 0):
    try:
        plans_api = _get_plans_api()
        response = plans_api.get_plans(
            limit=limit, offset=offset, include="summary,kpi,jobs"
        )
        print(f"DEBUG: plans_api.get_plans response: {response}")
        plans = response.get("plans", [])
        pagination = response.get("pagination", {})
        return plans, pagination
    except Exception:
        logging.exception("ui_plans_fetch_plans_failed")
        return [], {}


def _render_plans_page(
    request: Request,
    *,
    plans,
    pagination: dict | None = None,
    error: str | None = None,
    form_defaults: dict | None = None,
):
    print(f"DEBUG: _render_plans_page plans: {plans}")
    print(f"DEBUG: _render_plans_page pagination: {pagination}")
    canonical_options = _canonical_version_options()
    print(f"DEBUG: _render_plans_page canonical_options: {canonical_options}")
    scenario_options = _scenario_options()
    print(f"DEBUG: _render_plans_page scenario_options: {scenario_options}")
    return templates.TemplateResponse(
        request,
        "plans.html",
        {
            "subtitle": "Plan Versions",
            "plans": plans,
            "pagination": pagination or {},
            "error": error,
            "form_defaults": form_defaults or {},
            "canonical_options": canonical_options,
            "scenario_options": scenario_options,
        },
    )


@router.get("/ui/plans", response_class=HTMLResponse)
def ui_plans(request: Request, limit: int = 50, offset: int = 0):
    print("DEBUG: Calling _fetch_plan_rows")
    rows, pagination = _fetch_plan_rows(limit=limit, offset=offset)
    return _render_plans_page(request, plans=rows, pagination=pagination)


@router.get("/ui/plans/{version_id}", response_class=HTMLResponse)
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
    plan_jobs = get_plan_repository().fetch_plan_jobs(version_id=version_id)
    created_from_run_id: str | None = None
    if plan_jobs:
        created_from_run_id = plan_jobs[0].get("run_id")
    events = repo_fetch_override_events(get_plan_repository(), version_id)
    audit_events_raw = sorted(
        events,
        key=lambda e: (int(e.get("event_ts") or 0), e.get("event_id") or 0),
        reverse=True,
    )
    audit_events = summarize_audit_events(audit_events_raw[:200])  # 最新200件を初期表示
    plan_state_repo = latest_state_from_events(events)
    if plan_state_repo:
        plan_state = _normalize_plan_state(
            {**plan_state_repo, "source": "plan_repository"}
        )
    else:
        fallback_state = db.get_plan_artifact(version_id, "state.json")
        if isinstance(fallback_state, dict):
            plan_state = _normalize_plan_state({**fallback_state, "source": "legacy"})
        else:
            plan_state = None
    if plan_state is None:
        plan_state = _normalize_plan_state(
            {
                "state": "draft",
                "invalid": [],
                "source": "default",
            }
        )
    aggregate_rows = repo_fetch_aggregate_rows(get_plan_repository(), version_id)
    detail_rows = repo_fetch_detail_rows(get_plan_repository(), version_id)
    aggregate = {"rows": aggregate_rows}
    sku_week = {"rows": detail_rows}

    disagg_rows_sample = []
    try:
        disagg_rows_sample = detail_rows[:200]
    except Exception:
        disagg_rows_sample = []
    # schedule rows from mrp.json (first 200)
    schedule_rows_sample = []
    schedule_total = 0
    try:
        mrows = get_plan_repository().fetch_plan_series(version_id, level="mrp")
        schedule_total = len(mrows)
        schedule_rows_sample = mrows[:200]
    except Exception:
        mrows = []
        schedule_rows_sample = []
        schedule_total = 0

    config_version_id = ver.get("config_version_id")
    canonical_config = None
    canonical_meta: dict[str, Any] = {}
    canonical_counts: dict[str, int] = {}
    planning_summary: dict[str, Any] = {}
    if config_version_id:
        try:
            canonical_config = get_canonical_config(config_version_id)
            if canonical_config:
                canonical_meta = canonical_config.meta.model_dump()
                canonical_counts = {
                    "items": len(canonical_config.items),
                    "nodes": len(canonical_config.nodes),
                    "arcs": len(canonical_config.arcs),
                    "bom": len(canonical_config.bom),
                    "demands": len(canonical_config.demands),
                    "capacities": len(canonical_config.capacities),
                    "calendars": len(canonical_config.calendars),
                    "hierarchies": len(canonical_config.hierarchies),
                }
                planning_bundle = build_planning_inputs(canonical_config)
                agg_input = planning_bundle.aggregate_input
                planning_summary = {
                    "schema_version": agg_input.schema_version,
                    "demand_family": len(agg_input.demand_family),
                    "capacity": len(agg_input.capacity),
                    "mix_share": len(agg_input.mix_share),
                    "item_master": len(agg_input.item_master),
                    "inventory": len(agg_input.inventory),
                    "open_po": len(agg_input.open_po),
                }
        except CanonicalConfigNotFoundError:
            pass  # not found
        except Exception:
            logging.exception("ui_plan_detail_build_planning_inputs_failed")

    # Validate summary (MVP)
    validate = {}
    try:
        # 1) tolerance violations from reconciliation summary (before/after)
        tol_before = (recon.get("summary") or {}).get("tol_violations")
        tol_after = (recon_adj.get("summary") or {}).get("tol_violations")
        # 2) negative inventory counts from mrp rows
        neg_inv = 0
        frac_sched = 0
        for r in mrows:
            try:
                extra = json.loads(r.get("extra_json") or "{}")
                ohs = float(extra.get("on_hand_start") or 0)
                ohe = float(extra.get("on_hand_end") or 0)
                if ohe < 0 or ohs < 0:
                    neg_inv += 1
                sr = float(extra.get("scheduled_receipts") or 0)
                if abs(sr - round(sr)) > 1e-6:
                    frac_sched += 1
            except Exception:
                pass
        # 3) capacity violations from weekly_summary (adjusted_load > capacity)
        ws = get_plan_repository().fetch_plan_series(version_id, level="weekly_summary")
        cap_over = 0
        for r in ws:
            try:
                cap = float(r.get("capacity_used") or 0)
                adj = float(r.get("supply") or 0)
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
    kpi_rows = get_plan_repository().fetch_plan_kpis(version_id)
    kpi_preview: dict[str, Any] = {
        row["metric"]: row
        for row in kpi_rows
        if (row.get("bucket_type") or "total") == "total"
    }
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
            "created_from_run_id": created_from_run_id,
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
            "disagg_total": len(detail_rows),
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
            "audit_events": audit_events,
        },
    )


@router.post("/ui/plans/{version_id}/reconcile")
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
        _get_plans_api().post_plan_reconcile(version_id, body)  # reuse handler
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


@router.post("/ui/plans/{version_id}/plan_run_auto")
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
    lightweight: str | None = Form(default=None),
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
            "lightweight": _form_bool(lightweight),
            "config_version_id": config_version_id,
            "base_scenario_id": ver.get("base_scenario_id"),
            "source_run_id": source_meta.get("source_run_id"),
        },
    }
    runs_api = _get_runs_api()
    res = runs_api.post_runs(body)
    from fastapi.responses import RedirectResponse

    # 正常系でlocationへ誘導
    if isinstance(res, dict) and res.get("location"):
        return RedirectResponse(url=str(res.get("location")), status_code=303)
    # 失敗時は元画面へ
    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


_STEPS = ["draft", "aggregated", "disaggregated", "scheduled", "executed"]


@router.post("/ui/plans/{version_id}/state/advance")
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


@router.post("/ui/plans/{version_id}/state/invalidate")
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


@router.post("/ui/plans/run")
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
    res = _get_plans_api().post_plans_integrated_run(body)
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
