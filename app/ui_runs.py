from app.api import app
import logging
import json
from pathlib import Path
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app import db
from app.utils import ms_to_jst_str
from app.metrics import (
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    PLAN_DB_CAPACITY_TRIM_TOTAL,
    PLAN_DB_LAST_TRIM_TIMESTAMP,
)
from core.plan_repository import PlanRepository


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
        rows = [
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
                or ((r.get("summary") or {}).get("_plan_version_id")),
                "summary": r.get("summary") or {},
                "fill_rate": (r.get("summary") or {}).get("fill_rate"),
                "profit_total": (r.get("summary") or {}).get("profit_total"),
            }
            for r in rows
        ]
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
    elif config_version_id is not None:
        try:
            plans = db.list_plan_versions(limit=200)
            for p in plans:
                if p.get("config_version_id") == config_version_id:
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
        },
    )
