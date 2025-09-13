from app.api import app
import logging
import json
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def _get_registry():
    from app.run_registry import REGISTRY  # type: ignore

    return REGISTRY


from app.utils import ms_to_jst_str
from pathlib import Path

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
                "scenario_id": r.get("scenario_id"),
                "summary": r.get("summary") or {},
                "fill_rate": (r.get("summary") or {}).get("fill_rate"),
                "profit_total": (r.get("summary") or {}).get("profit_total"),
            }
            for r in rows
        ]
        return templates.TemplateResponse(
            "runs.html", {"request": request, "rows": rows, "subtitle": "Run Viewer"}
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
    cfg_json = rec.get("config_json")
    scenario_id = rec.get("scenario_id")
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
    try:
        # Highest priority: explicit back query
        back_q = request.query_params.get("back")  # type: ignore[attr-defined]
        if back_q and str(back_q).startswith("/ui/"):
            back_href = str(back_q)
            from_jobs = back_href.startswith("/ui/jobs")
        else:
            # Fallback: query from=jobs
            if request.query_params.get("from") == "jobs":  # type: ignore[attr-defined]
                from_jobs = True
            # Fallback: Referer header
            ref = request.headers.get("referer", "")
            if (not from_jobs) and ("/ui/jobs" in ref):
                from_jobs = True
                back_href = ref
            else:
                back_href = "/ui/jobs" if from_jobs else "/ui/runs"
    except Exception:
        pass
    return templates.TemplateResponse(
        "run_detail.html",
        {
            "request": request,
            "run_id": run_id,
            "summary": summary,
            "counts": counts,
            "config_id": cfg_id,
            "scenario_id": scenario_id,
            "config_json_str": cfg_json_str,
            "subtitle": "Run Viewer",
            "from_jobs": from_jobs,
            "back_href": back_href,
        },
    )
