from __future__ import annotations

from typing import Any, Dict
import logging
from fastapi import Body
from fastapi.responses import JSONResponse

from app.api import app
from app.metrics import RUNS_QUEUED


@app.post("/runs")
def post_runs(body: Dict[str, Any] = Body(...)):
    """Run API アダプタ（P-16 一時実装）
    - pipeline='integrated' を既存の plans/integrated/run or planning job に委譲
    - async=true の場合はジョブ投入、false（既定）は同期実行
    返却:
      - 同期: {status:'succeeded', run_type:'plan', version_id, artifacts, location}
      - 非同期: {status:'queued', job_id, location}
    """
    pipeline = (body.get("pipeline") or "integrated").lower()
    is_async = bool(body.get("async") or False)
    options: Dict[str, Any] = body.get("options") or {}

    if pipeline not in ("integrated",):
        return JSONResponse(status_code=400, content={"detail": "unsupported pipeline"})

    if is_async:
        # ジョブ投入（/planning/run_job 相当）
        try:
            from app.jobs import JOB_MANAGER

            params = {
                "input_dir": options.get("input_dir") or "samples/planning",
                "out_dir": options.get("out_dir"),
                "weeks": options.get("weeks") or 4,
                "round_mode": options.get("round_mode") or "int",
                "lt_unit": options.get("lt_unit") or "day",
                "version_id": options.get("version_id") or "",
                "cutover_date": options.get("cutover_date"),
                "recon_window_days": options.get("recon_window_days"),
                "anchor_policy": options.get("anchor_policy"),
                "calendar_mode": options.get("calendar_mode"),
                "max_adjust_ratio": options.get("max_adjust_ratio"),
                "carryover": options.get("carryover"),
                "carryover_split": options.get("carryover_split"),
                "apply_adjusted": bool(options.get("apply_adjusted") or False),
                "tol_abs": options.get("tol_abs"),
                "tol_rel": options.get("tol_rel"),
                "blend_split_next": options.get("blend_split_next"),
                "blend_weight_mode": options.get("blend_weight_mode"),
            }
            job_id = JOB_MANAGER.submit_planning(params)
            try:
                logging.info(
                    "run_queued",
                    extra={
                        "event": "run_queued",
                        "job_id": job_id,
                        "pipeline": pipeline,
                    },
                )
                try:
                    RUNS_QUEUED.inc()
                except Exception:
                    pass
            except Exception:
                pass
            return {
                "status": "queued",
                "job_id": job_id,
                "location": f"/ui/jobs/{job_id}",
            }
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": str(e)})

    # 同期実行（/plans/integrated/run 相当）
    try:
        from app import plans_api as _plans_api

        payload = {
            **options,
        }
        res = _plans_api.post_plans_integrated_run(payload)
        try:
            logging.info(
                "plan_created",
                extra={
                    "event": "plan_created",
                    "version_id": res.get("version_id"),
                    "pipeline": pipeline,
                },
            )
        except Exception:
            pass
        return {
            "status": "succeeded",
            "run_type": "plan",
            "version_id": res.get("version_id"),
            "artifacts": res.get("artifacts") or [],
            "location": f"/ui/plans/{res.get('version_id')}",
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
