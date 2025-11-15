from app.api import app
import logging
import json
from pathlib import Path
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app import db
from app.template_filters import register_format_filters
from app.utils import ms_to_jst_str
from app.metrics import (
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    PLAN_DB_CAPACITY_TRIM_TOTAL,
    PLAN_DB_LAST_TRIM_TIMESTAMP,
)
from core.plan_repository import PlanRepository
from core.config.storage import (
    get_planning_input_set,
    PlanningInputSetNotFoundError,
)


_PLAN_REPOSITORY = PlanRepository(
    db._conn,
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    PLAN_DB_CAPACITY_TRIM_TOTAL,
    PLAN_DB_LAST_TRIM_TIMESTAMP,
)


def _get_registry():
    from app.run_registry import REGISTRY  # type: ignore

    return REGISTRY


_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
register_format_filters(templates)


@app.get("/ui/runs", response_class=HTMLResponse)
def ui_runs(request: Request):
    try:
        REGISTRY = _get_registry()
        # DBバックエンドならページングAPIで取得を試みる（なければメモリ実装）
        rows = []
        if hasattr(REGISTRY, "list_page"):
            try:
                resp = REGISTRY.list_page(
                    offset=0,
                    limit=100,
                    sort="started_at",
                    order="desc",
                    schema_version=None,
                    config_id=None,
                    scenario_id=None,
                    detail=False,
                )
                rows = resp.get("runs") or []
            except Exception:
                rows = []
        if not rows:
            runs = REGISTRY.list_ids()
            rows = []
            for rid in runs:
                try:
                    rec = REGISTRY.get(rid) or {}
                    rows.append(rec)
                except Exception:
                    logging.exception("ui_runs_row_build_failed", extra={"run_id": rid})
                    continue
        enriched = []
        for r in rows:
            summary_obj = r.get("summary") or {}
            label = summary_obj.get("_input_set_label") or r.get("input_set_label")
            if isinstance(label, str):
                label = label.strip()
            enriched.append(
                {
                    "run_id": r.get("run_id"),
                    "started_at": r.get("started_at"),
                    "started_at_str": ms_to_jst_str(r.get("started_at")),
                    "duration_ms": r.get("duration_ms"),
                    "schema_version": r.get("schema_version"),
                    "config_id": r.get("config_id"),
                    "config_version_id": r.get("config_version_id"),
                    "scenario_id": r.get("scenario_id"),
                    "plan_version_id": r.get("plan_version_id")
                    or (summary_obj.get("_plan_version_id")),
                    "summary": summary_obj,
                    "fill_rate": summary_obj.get("fill_rate"),
                    "profit_total": summary_obj.get("profit_total"),
                    "input_set_label": label or None,
                }
            )
        rows = enriched
        return templates.TemplateResponse(
            request,
            "runs.html",
            {"rows": rows, "subtitle": "Run Viewer"},
        )
    except Exception:
        logging.exception("ui_runs_render_failed")
        # 元例外を再送出してミドルウェアでスタックを記録
        raise


@app.get("/ui/runs/{run_id}", response_class=HTMLResponse)
def ui_run_detail(request: Request, run_id: str):
    REGISTRY = _get_registry()
    rec = REGISTRY.get(run_id)
    if not rec:
        # fallback to DB
        try:
            from app import db as _db

            with _db._conn() as c:  # type: ignore[attr-defined]
                row = c.execute(
                    "SELECT * FROM runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if row:
                    import json as _json

                    rec = {
                        "run_id": row["run_id"],
                        "summary": _json.loads(row["summary"] or "{}"),
                        "results": _json.loads(row["results"] or "[]"),
                        "daily_profit_loss": _json.loads(
                            row["daily_profit_loss"] or "[]"
                        ),
                        "cost_trace": _json.loads(row["cost_trace"] or "[]"),
                        "config_id": row["config_id"],
                        "config_version_id": (
                            row["config_version_id"]
                            if "config_version_id" in row.keys()
                            else None
                        ),
                        "scenario_id": row["scenario_id"],
                    }
        except Exception:
            rec = None
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    summary = rec.get("summary") or {}
    counts = {
        "results_len": len(rec.get("results") or []),
        "pl_len": len(rec.get("daily_profit_loss") or []),
        "trace_len": len(rec.get("cost_trace") or []),
    }
    cfg_id = rec.get("config_id")
    config_version_id = rec.get("config_version_id")
    cfg_json = rec.get("config_json")
    scenario_id = rec.get("scenario_id")
    plan_version_id = rec.get("plan_version_id") or (
        summary.get("_plan_version_id") if isinstance(summary, dict) else None
    )
    plan_job_id = rec.get("plan_job_id")
    plan_rec = None

    input_set_label: str | None = None
    if isinstance(summary, dict):
        raw_summary_label = summary.get("_input_set_label") or summary.get(
            "input_set_label"
        )
        if isinstance(raw_summary_label, str) and raw_summary_label.strip():
            input_set_label = raw_summary_label.strip()
    input_set_artifact = (
        db.get_plan_artifact(plan_version_id, "planning_input_set.json")
        if plan_version_id
        else None
    )
    artifact_source = None
    artifact_updated_at = None
    if isinstance(input_set_artifact, dict):
        raw_art_label = input_set_artifact.get("label") or input_set_artifact.get(
            "input_set_label"
        )
        if (
            not input_set_label
            and isinstance(raw_art_label, str)
            and raw_art_label.strip()
        ):
            input_set_label = raw_art_label.strip()
        artifact_source = input_set_artifact.get("source")
        try:
            artifact_updated_at = int(input_set_artifact.get("updated_at"))
        except (TypeError, ValueError):
            artifact_updated_at = None

    plan_kpi_summary: dict[str, float] = {}
    if plan_version_id:
        try:
            kpi_totals = _PLAN_REPOSITORY.fetch_plan_kpi_totals([plan_version_id])
            if plan_version_id in kpi_totals:
                plan_kpi_summary = kpi_totals[plan_version_id]
        except Exception:
            logging.exception("ui_run_detail_fetch_kpi_failed")
    try:
        cfg_json_str = (
            json.dumps(cfg_json, ensure_ascii=False, indent=2)
            if cfg_json is not None
            else ""
        )
    except Exception:
        cfg_json_str = ""
    # Back link context (prefer explicit query from=jobs; fallback to Referer)
    # Determine back link target
    from_jobs = False
    back_href = "/ui/runs"
    back_label = "\u2190 Back to runs"  # default with left arrow
    try:
        # Highest priority: explicit back query
        back_q = request.query_params.get("back")  # type: ignore[attr-defined]
        if back_q and str(back_q).startswith("/ui/"):
            back_href = str(back_q)
            from_jobs = back_href.startswith("/ui/jobs")
            if back_href.startswith("/ui/jobs/"):
                back_label = "\u2190 Back to job detail"
            elif back_href.startswith("/ui/jobs"):
                back_label = "\u2190 Back to jobs"
        else:
            # Fallback: query from=jobs
            if request.query_params.get("from") == "jobs":  # type: ignore[attr-defined]
                from_jobs = True
            # Fallback: Referer header
            ref = request.headers.get("referer", "")
            if (not from_jobs) and ("/ui/jobs" in ref):
                from_jobs = True
                back_href = ref
                if "/ui/jobs/" in ref:
                    back_label = "\u2190 Back to job detail"
                else:
                    back_label = "\u2190 Back to jobs"
            else:
                back_href = "/ui/jobs" if from_jobs else "/ui/runs"
                if from_jobs:
                    back_label = "\u2190 Back to jobs"
    except Exception:
        pass
    matching_plans: list[dict] = []
    effective_config_version_id = config_version_id
    if plan_version_id:
        plan_rec = db.get_plan_version(plan_version_id)
        if plan_rec:
            created = plan_rec.get("created_at")
            matching_plans.append(
                {
                    "version_id": plan_version_id,
                    "status": plan_rec.get("status"),
                    "created_at": created,
                    "created_at_str": ms_to_jst_str(created),
                }
            )
            if effective_config_version_id is None:
                effective_config_version_id = plan_rec.get("config_version_id")
    if (not plan_version_id) and (effective_config_version_id is not None):
        try:
            plans = db.list_plan_versions(limit=200)
            for p in plans:
                if p.get("config_version_id") == effective_config_version_id:
                    created = p.get("created_at")
                    matching_plans.append(
                        {
                            "version_id": p.get("version_id"),
                            "status": p.get("status"),
                            "created_at": created,
                            "created_at_str": ms_to_jst_str(created),
                        }
                    )
        except Exception:
            matching_plans = []
    if config_version_id is None and effective_config_version_id is not None:
        config_version_id = effective_config_version_id

    storage_input_set = None
    missing_input_set = False
    input_set_inferred = False

    def _load_input_set_by_label(label: str):
        query_kwargs = {"label": label, "include_aggregates": False}
        if effective_config_version_id is not None:
            query_kwargs["config_version_id"] = effective_config_version_id
        return get_planning_input_set(**query_kwargs)

    if input_set_label:
        try:
            storage_input_set = _load_input_set_by_label(input_set_label)
        except PlanningInputSetNotFoundError:
            missing_input_set = True
        except Exception:
            logging.exception(
                "ui_run_detail_load_input_set_failed",
                extra={"run_id": run_id, "label": input_set_label},
            )
    if storage_input_set is None and effective_config_version_id is not None:
        need_infer = (not input_set_label) or missing_input_set
        if need_infer:
            for status_filter in ("ready", None):
                try:
                    kwargs = {
                        "config_version_id": effective_config_version_id,
                        "include_aggregates": False,
                    }
                    if status_filter:
                        kwargs["status"] = status_filter
                    storage_input_set = get_planning_input_set(**kwargs)
                    input_set_label = storage_input_set.label
                    input_set_inferred = True
                    missing_input_set = False
                    break
                except PlanningInputSetNotFoundError:
                    continue
                except Exception:
                    logging.exception(
                        "ui_run_detail_infer_input_set_failed",
                        extra={
                            "run_id": run_id,
                            "config_version_id": effective_config_version_id,
                        },
                    )
                    break

    input_set_info = {
        "label": input_set_label,
        "config_version_id": effective_config_version_id,
        "plan_version_id": plan_version_id,
        "status": None,
        "source": artifact_source,
        "updated_at": artifact_updated_at,
        "updated_at_str": (
            ms_to_jst_str(artifact_updated_at) if artifact_updated_at else None
        ),
        "id": None,
        "legacy": False,
        "missing": False,
        "inferred": input_set_inferred,
    }
    if storage_input_set:
        updated_at = storage_input_set.updated_at
        input_set_info.update(
            {
                "id": storage_input_set.id,
                "status": storage_input_set.status,
                "source": storage_input_set.source or artifact_source,
                "updated_at": updated_at or input_set_info.get("updated_at"),
                "updated_at_str": (
                    ms_to_jst_str(updated_at)
                    if updated_at
                    else input_set_info.get("updated_at_str")
                ),
                "config_version_id": storage_input_set.config_version_id,
            }
        )
    elif not input_set_label:
        input_set_info["legacy"] = True
    if missing_input_set and not input_set_inferred:
        input_set_info["missing"] = True

    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "run_id": run_id,
            "summary": summary,
            "counts": counts,
            "config_id": cfg_id,
            "config_version_id": config_version_id,
            "scenario_id": scenario_id,
            "plan_version_id": plan_version_id,
            "plan_job_id": plan_job_id,
            "plan_kpi_summary": plan_kpi_summary,
            "config_json_str": cfg_json_str,
            "subtitle": "Run Viewer",
            "from_jobs": from_jobs,
            "back_href": back_href,
            "back_label": back_label,
            "matching_plans": matching_plans,
            "input_set_info": input_set_info,
        },
    )
