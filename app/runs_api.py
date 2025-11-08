from __future__ import annotations

from typing import Any, Dict
import logging
from fastapi import Body
from fastapi.responses import JSONResponse

from app.api import app
from app.metrics import RUNS_QUEUED, LEGACY_MODE_RUNS_TOTAL


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
    options_raw: Dict[str, Any] = body.get("options") or {}

    # 軽量バリデーション/型補正（エラーは400）
    def _as_int(x, default=None):
        if x is None:
            return default
        try:
            return int(x)
        except Exception:
            return None

    def _as_float(x, default=None):
        if x is None:
            return default
        try:
            return float(x)
        except Exception:
            return None

    def _as_str(x, default=None):
        if x is None:
            return default
        return str(x)

    def _as_bool(x, default=False):
        if x is None:
            return default
        if isinstance(x, bool):
            return x
        if isinstance(x, (int, float)):
            return bool(x)
        if isinstance(x, str):
            s = x.strip().lower()
            if s in ("1", "true", "yes", "on"):
                return True
            if s in ("0", "false", "no", "off"):
                return False
        return default

    # 正規化
    options: Dict[str, Any] = {}
    options["out_dir"] = options_raw.get("out_dir")
    options["weeks"] = _as_int(options_raw.get("weeks") or 4)
    options["round_mode"] = _as_str(options_raw.get("round_mode") or "int")
    options["lt_unit"] = _as_str(options_raw.get("lt_unit") or "day")
    options["version_id"] = _as_str(options_raw.get("version_id") or "")
    options["base_scenario_id"] = _as_int(options_raw.get("base_scenario_id"))
    options["source_run_id"] = options_raw.get("source_run_id")
    options["cutover_date"] = options_raw.get("cutover_date")
    options["recon_window_days"] = _as_int(options_raw.get("recon_window_days"))
    options["anchor_policy"] = options_raw.get("anchor_policy")
    options["calendar_mode"] = options_raw.get("calendar_mode")
    options["max_adjust_ratio"] = _as_float(options_raw.get("max_adjust_ratio"))
    options["carryover"] = options_raw.get("carryover")
    options["carryover_split"] = _as_float(options_raw.get("carryover_split"))
    options["apply_adjusted"] = _as_bool(options_raw.get("apply_adjusted"), False)
    options["lightweight"] = _as_bool(options_raw.get("lightweight"), False)
    options["tol_abs"] = _as_float(options_raw.get("tol_abs"))
    options["tol_rel"] = _as_float(options_raw.get("tol_rel"))
    options["blend_split_next"] = _as_float(options_raw.get("blend_split_next"))
    options["blend_weight_mode"] = options_raw.get("blend_weight_mode")
    options["config_version_id"] = _as_int(options_raw.get("config_version_id"))
    options["input_set_label"] = _as_str(options_raw.get("input_set_label"))

    # Legacyモードの検知
    if not options.get("input_set_label"):
        logging.warning(
            "legacy_mode_detected",
            extra={
                "entrypoint": "/runs",
                "config_version_id": options.get("config_version_id"),
                "base_scenario_id": options.get("base_scenario_id"),
            },
        )
        try:
            LEGACY_MODE_RUNS_TOTAL.labels(entrypoint="/runs").inc()
        except Exception:
            logging.exception("failed_to_inc_legacy_mode_metric")

    # 検証
    if pipeline not in ("integrated",):
        return JSONResponse(status_code=400, content={"detail": "unsupported pipeline"})
    if options["weeks"] is None or options["weeks"] <= 0:
        return JSONResponse(
            status_code=400, content={"detail": "weeks must be positive integer"}
        )
    if options["lt_unit"] not in ("day", "week"):
        return JSONResponse(
            status_code=400, content={"detail": "lt_unit must be 'day' or 'week'"}
        )
    rm = options.get("round_mode") or "int"
    if rm not in ("none", "int", "dec1", "dec2"):
        return JSONResponse(
            status_code=400,
            content={"detail": "round_mode must be one of none|int|dec1|dec2"},
        )
    ap = options.get("anchor_policy")
    if ap is not None and ap != "" and ap not in ("DET_near", "AGG_far", "blend"):
        return JSONResponse(
            status_code=400,
            content={"detail": "anchor_policy must be one of DET_near|AGG_far|blend"},
        )
    cm = options.get("calendar_mode")
    if cm is not None and cm != "" and cm not in ("simple", "iso"):
        return JSONResponse(
            status_code=400,
            content={"detail": "calendar_mode must be one of simple|iso"},
        )
    co = options.get("carryover")
    if co is not None and co != "" and co not in ("auto", "prev", "next", "both"):
        return JSONResponse(
            status_code=400,
            content={"detail": "carryover must be one of auto|prev|next|both"},
        )
    if options.get("carryover_split") is not None:
        cs = float(options["carryover_split"])
        if cs < 0 or cs > 1:
            return JSONResponse(
                status_code=400,
                content={"detail": "carryover_split must be between 0 and 1"},
            )
    if options.get("tol_abs") is not None and float(options["tol_abs"]) < 0:
        return JSONResponse(status_code=400, content={"detail": "tol_abs must be >= 0"})
    if options.get("tol_rel") is not None and float(options["tol_rel"]) < 0:
        return JSONResponse(status_code=400, content={"detail": "tol_rel must be >= 0"})
    if (
        options.get("max_adjust_ratio") is not None
        and float(options["max_adjust_ratio"]) < 0
    ):
        return JSONResponse(
            status_code=400, content={"detail": "max_adjust_ratio must be >= 0"}
        )
    if options.get("blend_split_next") is not None:
        bs = float(options["blend_split_next"])
        if bs < 0 or bs > 1:
            return JSONResponse(
                status_code=400,
                content={"detail": "blend_split_next must be between 0 and 1"},
            )
    bwm = options.get("blend_weight_mode")
    if bwm is not None and bwm != "" and bwm not in ("tri", "lin", "quad"):
        return JSONResponse(
            status_code=400,
            content={"detail": "blend_weight_mode must be one of tri|lin|quad"},
        )

    if pipeline not in ("integrated",):
        return JSONResponse(status_code=400, content={"detail": "unsupported pipeline"})
    if options.get("config_version_id") is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "config_version_id is required for integrated pipeline"},
        )

    if is_async:
        # ジョブ投入（/planning/run_job 相当）
        try:
            from app.jobs import JOB_MANAGER

            params = options
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
                "input_set_label": options.get("input_set_label"),
            }
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": str(e)})

    # 同期実行（/plans/integrated/run 相当）
    try:
        from app import plans_api as _plans_api

        res = _plans_api.post_plans_create_and_execute(options)
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
            "config_version_id": res.get("config_version_id"),
            "artifacts": res.get("artifacts") or [],
             "input_set_label": res.get("input_set_label"),
            "location": f"/ui/plans/{res.get('version_id')}",
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
