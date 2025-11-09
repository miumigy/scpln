from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app import db
from app.metrics import (
    INPUT_SET_DIFF_CACHE_HITS_TOTAL,
    INPUT_SET_DIFF_CACHE_STALE_TOTAL,
    INPUT_SET_DIFF_JOBS_TOTAL,
    PLAN_CARRYOVER_EXPORT_TOTAL,
    PLAN_COMPARE_EXPORT_TOTAL,
    PLAN_DB_CAPACITY_TRIM_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    PLAN_DB_LAST_TRIM_TIMESTAMP,
    PLAN_DB_WRITE_LATENCY,
    PLAN_SCHEDULE_EXPORT_TOTAL,
    PLAN_SERIES_ROWS_TOTAL,
    PLANS_RECONCILED_TOTAL,
    PLANS_VIEWED_TOTAL,
)
from app.template_filters import register_format_filters
from app.utils import ms_to_jst_str
from core.config import build_planning_inputs
from core.config.importer import import_planning_inputs
from core.config.storage import (
    CanonicalConfigNotFoundError,
    get_canonical_config,
    get_planning_input_set,
    list_canonical_version_summaries,
    list_planning_input_set_events,
    list_planning_input_sets,
    log_planning_input_set_event,
    PlanningInputSetNotFoundError,
    update_planning_input_set,
)
from core.plan_repository import PlanRepository
from core.plan_repository_views import (
    fetch_aggregate_rows as repo_fetch_aggregate_rows,
    fetch_detail_rows as repo_fetch_detail_rows,
    fetch_override_events as repo_fetch_override_events,
    latest_state_from_events,
    summarize_audit_events,
)


def table_exists(db_conn, name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = db_conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cursor.fetchone() is not None


router = APIRouter()


_BASE_DIR = Path(__file__).resolve().parents[1]

_DIFF_CACHE_DIR = _BASE_DIR / "tmp" / "input_set_diffs"
_DIFF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_DIFF_CACHE_TTL_SECONDS = 600
_DIFF_LOCK_TTL_SECONDS = 600
_DIFF_TABLE_LIMIT = 500
_SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
_NAT_SORT_TOKEN = re.compile(r"\d+|\D+")
_DELTA_SORT_KEYS = (
    "period",
    "family_code",
    "sku_code",
    "resource_code",
    "node_code",
    "item_code",
    "due_date",
    "metric_code",
)


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
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
register_format_filters(templates)


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
        state.get("approved_at") or state.get("submitted_at") or state.get("timestamp")
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
    has_data: bool = True,
):
    canonical_options = _canonical_version_options()
    scenario_options = _scenario_options()
    try:
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
                "has_data": has_data,
            },
        )
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        raise


@router.get("/ui/plans", response_class=HTMLResponse)
def ui_plans(request: Request, limit: int = 50, offset: int = 0):
    has_data = False
    rows, pagination = [], {}
    if table_exists(db._conn(), "plan_versions"):
        rows, pagination = _fetch_plan_rows(limit=limit, offset=offset)
        if rows:
            has_data = True

    # paginationがNoneになる可能性を考慮し、空の辞書をデフォルトとする
    pagination = pagination if pagination is not None else {}

    return _render_plans_page(
        request, plans=rows, pagination=pagination, has_data=has_data
    )


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
        from app.run_registry import REGISTRY

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
            PLANS_VIEWED_TOTAL.inc()
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
                PLANS_RECONCILED_TOTAL.inc()
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        pass
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


@router.post("/ui/plans/{version_id}/execute_auto")
def ui_plan_execute_auto(
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
    """Plan & Execute (auto completion): 既存Planの情報を可能な範囲で引き継ぎ、/runs を呼び出して新規Planを生成。
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
    if isinstance(res, dict):
        try:
            PLANS_CREATED_TOTAL.inc()
        except Exception:
            pass
    from fastapi.responses import RedirectResponse

    # 正常系でlocationへ誘導
    if isinstance(res, dict) and res.get("location"):
        return RedirectResponse(url=str(res.get("location")), status_code=303)
    # 失敗時は元画面へ
    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


@router.post("/ui/plans/{version_id}/delete")
def ui_plan_delete(version_id: str, request: Request):
    from fastapi.responses import RedirectResponse

    db.init_db()
    ver = db.get_plan_version(version_id)
    if not ver:
        return RedirectResponse(
            url="/ui/plans?error=plan_not_found",
            status_code=303,
        )
    try:
        get_plan_repository().delete_plan(version_id)
    except Exception:
        logging.exception(
            "ui_plan_delete_repo_failed",
            extra={"version_id": version_id},
        )
        return RedirectResponse(
            url=f"/ui/plans/{version_id}?error=delete_failed",
            status_code=303,
        )
    for cleanup, phase in (
        (db.delete_plan_artifacts, "artifacts"),
        (db.clear_plan_version_from_runs, "runs"),
        (db.delete_plan_version, "plan_version"),
    ):
        try:
            cleanup(version_id)
        except Exception:
            logging.exception(
                "ui_plan_delete_cleanup_failed",
                extra={"version_id": version_id, "phase": phase},
            )
    logging.info(
        "plan_version_deleted",
        extra={"version_id": version_id, "actor": "ui_plans"},
    )
    return RedirectResponse(url="/ui/plans", status_code=303)


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


@router.post("/ui/plans/create_and_execute")
def ui_plans_create_and_execute(
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
        rows, pagination = _fetch_plan_rows()
        return _render_plans_page(
            request,
            plans=rows,
            pagination=pagination,
            error="Canonical設定バージョンを選択してください。",
            form_defaults=form_defaults,
        )

    # version_idを事前に採番
    import time
    import uuid

    ts = int(time.time())
    version_id = f"v{ts}-{uuid.uuid4().hex[:8]}"

    # runs_api を呼び出すように変更
    body = {
        "pipeline": "integrated",
        "async": True,  # 非同期実行を指定
        "options": {
            "version_id": version_id,  # 生成したversion_idを渡す
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
        },
    }

    res = _get_runs_api().post_runs(body)
    if isinstance(res, dict):
        try:
            PLANS_CREATED_TOTAL.inc()
        except Exception:
            pass
    from fastapi.responses import RedirectResponse

    # 正常系でlocationへ誘導 (非同期の場合は /ui/jobs/{job_id})
    if isinstance(res, dict) and res.get("location"):
        return RedirectResponse(url=str(res.get("location")), status_code=303)

    # 失敗時はエラーメッセージを表示
    error_message = "ジョブの投入に失敗しました。"
    if hasattr(res, "body"):
        try:
            payload = json.loads(res.body)
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if isinstance(detail, str) and detail:
                error_message = detail
        except Exception:
            pass
    elif isinstance(res, dict) and res.get("detail"):
        error_message = res.get("detail")

    rows, pagination = _fetch_plan_rows()
    return _render_plans_page(
        request,
        plans=rows,
        pagination=pagination,
        error=error_message,
        form_defaults=form_defaults,
    )

def _safe_slug(value: str | None) -> str:
    if not value:
        return "unknown"
    slug = _SLUG_PATTERN.sub("-", value).strip("-").lower()
    return slug or "unknown"


def _naturalize_value(value: Any) -> tuple:
    if value is None:
        return (2, "")
    if isinstance(value, (int, float)):
        return (0, value)
    text = str(value).strip()
    if not text:
        return (1, "")
    tokens = _NAT_SORT_TOKEN.findall(text)
    if not tokens:
        return (1, text.lower())
    normalized: list[tuple[str, Any]] = []
    for token in tokens:
        if token.isdigit():
            normalized.append(("n", int(token)))
        else:
            normalized.append(("s", token.lower()))
    return tuple(normalized)


def _prepare_delta_rows(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    limit: int | None = 200,
) -> list[Mapping[str, Any]]:
    """
    Diffレポートの行を自然順ソートし、必要に応じて件数を制限する。
    """
    if not rows:
        return []
    sorted_rows = sorted(
        rows,
        key=lambda row: tuple(_naturalize_value(row.get(key)) for key in _DELTA_SORT_KEYS),
    )
    if limit is not None:
        return list(sorted_rows[:limit])
    return list(sorted_rows)


def _list_canonical_options() -> list[dict[str, object]]:
    summaries = list_canonical_version_summaries(limit=100)
    options: list[dict[str, object]] = []
    for summary in summaries:
        meta = summary.meta
        version_id = meta.version_id
        if version_id is None:
            continue
        display_name = meta.name or f"Version {version_id}"
        num_calendars = summary.counts.get("calendars", 0)
        options.append(
            {
                "id": version_id,
                "label": f"{display_name} (v{version_id})",
                "num_calendars": num_calendars,
            }
        )
    return options


def _diff_cache_paths(label: str, other_label: str) -> tuple[Path, Path]:
    key = f"{_safe_slug(label)}__{_safe_slug(other_label)}"
    cache_path = _DIFF_CACHE_DIR / f"{key}.json"
    lock_path = _DIFF_CACHE_DIR / f"{key}.lock"
    return cache_path, lock_path


def _load_cached_diff(cache_path: Path) -> tuple[dict | None, int | None]:
    if not cache_path.exists():
        return None, None
    age = time.time() - cache_path.stat().st_mtime
    if age > _DIFF_CACHE_TTL_SECONDS:
        try:
            INPUT_SET_DIFF_CACHE_STALE_TOTAL.inc()
        except Exception:
            pass
        return None, None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        generated_at = int(cache_path.stat().st_mtime * 1000)
        try:
            INPUT_SET_DIFF_CACHE_HITS_TOTAL.inc()
        except Exception:
            pass
        return data, generated_at
    except Exception:
        logging.exception("input_set_diff_cache_load_failed", extra={"cache": str(cache_path)})
        try:
            INPUT_SET_DIFF_CACHE_STALE_TOTAL.inc()
        except Exception:
            pass
        return None, None


def _is_lock_active(lock_path: Path) -> bool:
    if not lock_path.exists():
        return False
    age = time.time() - lock_path.stat().st_mtime
    if age > _DIFF_LOCK_TTL_SECONDS:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            logging.warning("input_set_diff_lock_cleanup_failed", exc_info=True)
        return False
    return True


def _schedule_diff_generation(
    background_tasks: BackgroundTasks,
    label: str,
    other_label: str,
    cache_path: Path,
    lock_path: Path,
) -> None:
    try:
        lock_path.touch()
    except Exception:
        logging.warning("input_set_diff_lock_touch_failed", exc_info=True)
    background_tasks.add_task(_generate_diff_report, label, other_label, cache_path, lock_path)


def _generate_diff_report(label: str, other_label: str, cache_path: Path, lock_path: Path) -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="input-set-diff-"))
    try:
        script_path = str(_BASE_DIR / "scripts" / "export_planning_inputs.py")
        args = [
            sys.executable,
            script_path,
            "--label",
            label,
            "--diff-against",
            other_label,
            "--output-dir",
            str(temp_dir),
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONPATH", str(_BASE_DIR))
        result = subprocess.run(
            args,
            cwd=str(_BASE_DIR),
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logging.error(
                "input_set_diff_job_failed",
                extra={"label": label, "against": other_label, "stderr": result.stderr},
            )
            try:
                INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
            except Exception:
                pass
            return
        diff_path = temp_dir / "diff_report.json"
        if diff_path.exists():
            cache_path.write_text(diff_path.read_text(encoding="utf-8"), encoding="utf-8")
            try:
                INPUT_SET_DIFF_JOBS_TOTAL.labels(result="success").inc()
            except Exception:
                pass
        else:
            logging.error(
                "input_set_diff_job_missing_output",
                extra={"label": label, "against": other_label},
            )
            try:
                INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
            except Exception:
                pass
    except Exception:
        logging.exception(
            "input_set_diff_job_exception",
            extra={"label": label, "against": other_label},
        )
        try:
            INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
        except Exception:
            pass
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            logging.warning("input_set_diff_temp_cleanup_failed", exc_info=True)
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            logging.warning("input_set_diff_lock_remove_failed", exc_info=True)

@router.get("/ui/plans/input_sets/upload", response_class=HTMLResponse)
def ui_get_input_set_upload_form(request: Request):
    canonical_options = _list_canonical_options()
    return templates.TemplateResponse(
        request,
        "input_set_upload.html",
        {
            "subtitle": "Upload Input Set",
            "canonical_options": canonical_options,
        },
    )

@router.post("/ui/plans/input_sets/upload", response_class=HTMLResponse)
async def ui_post_input_set_upload(
    request: Request,
    config_version_id: int = Form(...),
    label: str = Form(...),
    files: list[UploadFile] = File(...),
):
    if not label or not label.strip():
        raise HTTPException(status_code=400, detail="Input Set Label is required.")
    if not config_version_id:
        raise HTTPException(status_code=400, detail="Canonical Config Version is required.")

    if not files or all((not f.filename) for f in files):
        raise HTTPException(status_code=400, detail="At least one CSV file is required.")

    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="input-set-upload-"))
        uploaded_file_paths = []
        for file in files:
            file_path = temp_dir / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_file_paths.append(file_path)
        
        logging.info(f"Uploaded files for input set '{label}' (config_version_id: {config_version_id}) to: {temp_dir}")
        for p in uploaded_file_paths:
            logging.info(f" - {p}")

        # ここで検証ロジックを呼び出す
        # 現時点では成功としてリダイレクト
        try:
            result = import_planning_inputs(
                directory=temp_dir,
                config_version_id=config_version_id,
                label=label,
                apply_mode="replace",  # UIからのアップロードは常にreplaceモードとする
                validate_only=False,
                status="draft",
                source="ui",
                created_by="ui_upload_form",
            )
            if result["status"] == "error":
                raise HTTPException(status_code=400, detail=result["message"])

            return RedirectResponse(url=f"/ui/plans/input_sets/{label}", status_code=303)
        except HTTPException:
            raise # re-raise HTTPException
        except Exception as e:
            logging.exception("Failed to import planning inputs.")
            raise HTTPException(status_code=500, detail=f"Failed to import planning inputs: {e}")
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir)

@router.get("/ui/plans/input_sets", response_class=HTMLResponse)
def ui_list_input_sets(request: Request):
    status_query = (request.query_params.get("status") or "ready").lower()
    status_filter = None if status_query == "all" else status_query
    input_sets = list_planning_input_sets(status=status_filter)
    status_options = [
        ("all", "All"),
        ("draft", "Draft"),
        ("ready", "Ready"),
        ("archived", "Archived"),
    ]
    return templates.TemplateResponse(
        request,
        "input_sets.html",
        {
            "subtitle": "Planning Input Sets",
            "input_sets": input_sets,
            "status_options": status_options,
            "selected_status": status_query,
        },
    )

@router.get("/ui/plans/input_sets/{label}", response_class=HTMLResponse)
def ui_get_input_set_detail(label: str, request: Request):
    try:
        input_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")
    events = list_planning_input_set_events(input_set.id, limit=100) if input_set.id else []

    return templates.TemplateResponse(
        request,
        "input_set_detail.html",
        {
            "subtitle": f"Input Set: {label}",
            "input_set": input_set,
            "input_set_events": events,
        },
    )


@router.post("/ui/plans/input_sets/{label}/review", response_class=HTMLResponse)
async def ui_review_input_set(
    label: str,
    request: Request,
    action: str = Form(...),
    reviewer: str = Form(""),
    review_comment: str = Form(""),
):
    try:
        input_set = get_planning_input_set(label=label, include_aggregates=False)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    if input_set.status == "archived":
        raise HTTPException(status_code=400, detail="Archived input sets cannot be reviewed.")

    reviewer_value = reviewer.strip() or "ui_reviewer"
    comment_value = review_comment.strip() or None

    try:
        if action == "approve":
            update_planning_input_set(
                input_set.id,
                status="ready",
                approved_by=reviewer_value,
                approved_at=int(time.time() * 1000),
                review_comment=comment_value,
            )
            log_planning_input_set_event(
                input_set.id,
                action="approve",
                actor=reviewer_value,
                comment=comment_value,
                metadata={"source": "ui_review"},
            )
        elif action == "revert":
            update_planning_input_set(
                input_set.id,
                status="draft",
                approved_by=None,
                approved_at=None,
                review_comment=comment_value,
            )
            log_planning_input_set_event(
                input_set.id,
                action="revert",
                actor=reviewer_value,
                comment=comment_value,
                metadata={"source": "ui_review"},
            )
        else:
            raise HTTPException(status_code=400, detail="Unsupported review action.")
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    return RedirectResponse(url=f"/ui/plans/input_sets/{label}", status_code=303)


@router.get("/ui/plans/input_sets/{label}/diff", response_class=HTMLResponse)
def ui_plan_input_set_diff(
    label: str,
    request: Request,
    against: str | None = Query(None, description="Label of the input set to compare against. Defaults to latest ready set."),
):
    background_tasks = BackgroundTasks()

    try:
        current_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    other_label = against
    other_set = None
    if not other_label:
        summaries = list_planning_input_sets(
            config_version_id=current_set.config_version_id,
            status="ready",
            limit=10,
        )
        for s in sorted(summaries, key=lambda x: x.updated_at or 0, reverse=True):
            if s.label != label:
                other_label = s.label
                break

    if other_label:
        try:
            other_set = get_planning_input_set(label=other_label, include_aggregates=True)
        except PlanningInputSetNotFoundError:
            other_set = None

    diff_report = None
    diff_generated_at = None
    diff_generating = False
    if other_set and other_label:
        cache_path, lock_path = _diff_cache_paths(label, other_label)
        diff_report, diff_generated_at = _load_cached_diff(cache_path)
        if diff_report is None:
            diff_generating = _is_lock_active(lock_path)
            if not diff_generating:
                _schedule_diff_generation(
                    background_tasks,
                    label,
                    other_label,
                    cache_path,
                    lock_path,
                )
                diff_generating = True
        elif isinstance(diff_report, dict):
            for section in diff_report.values():
                if not isinstance(section, dict):
                    continue
                rows_added = section.get("added")
                rows_removed = section.get("removed")
                if rows_added is not None:
                    section["added"] = _prepare_delta_rows(rows_added, limit=_DIFF_TABLE_LIMIT)
                if rows_removed is not None:
                    section["removed"] = _prepare_delta_rows(rows_removed, limit=_DIFF_TABLE_LIMIT)

    return templates.TemplateResponse(
        request,
        "input_set_diff.html",
        {
            "subtitle": f"Input Set Diff: {label}",
            "current_set": current_set,
            "other_set": other_set,
            "diff_report": diff_report,
            "diff_generating": diff_generating,
            "diff_generated_at": diff_generated_at,
        },
        background=background_tasks,
    )
