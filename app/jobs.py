import threading
import queue
import time
import csv
import json
from uuid import uuid4
from typing import Any, Dict, Optional, Tuple
import os
import sys
import logging
from pathlib import Path

from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
from app.run_registry import REGISTRY, record_canonical_run
from app import db
from prometheus_client import Counter as _Counter, Histogram as _Histogram
from app.metrics import (
    PLAN_DB_WRITE_TOTAL,
    PLAN_DB_WRITE_ERROR_TOTAL,
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    PLAN_DB_CAPACITY_TRIM_TOTAL,
    PLAN_DB_LAST_TRIM_TIMESTAMP,
)
from engine.aggregation import aggregate_by_time, rollup_axis
from core.config import CanonicalConfig, PlanningDataBundle, build_planning_inputs
from core.config.storage import (
    CanonicalConfigNotFoundError,
    load_canonical_config_from_db,
)
from core.plan_repository import PlanRepository, PlanRepositoryError
from core.plan_repository_builders import (
    build_plan_kpis_from_aggregate,
    build_plan_series,
)


_STORAGE_CHOICES = {"db", "files", "both"}

JOBS_ENABLED = os.getenv("JOBS_ENABLED", "1") == "1"
JOBS_WORKERS = int(os.getenv("JOBS_WORKERS", "1") or 1)

JOBS_ENQUEUED = _Counter(
    "jobs_enqueued_total", "Total jobs enqueued", labelnames=("type",)
)
JOBS_COMPLETED = _Counter(
    "jobs_completed_total", "Total jobs completed", labelnames=("type",)
)
JOBS_FAILED = _Counter("jobs_failed_total", "Total jobs failed", labelnames=("type",))
JOBS_DURATION = _Histogram(
    "jobs_duration_seconds",
    "Job execution duration in seconds",
    labelnames=("type",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, float("inf")),
)


def _storage_mode(value: Optional[str] = None) -> str:
    if value:
        mode = str(value).lower()
        if mode in _STORAGE_CHOICES:
            return mode
    env_mode = os.getenv("PLAN_STORAGE_MODE", "both").lower()
    if env_mode in _STORAGE_CHOICES:
        return env_mode
    return "both"


def _should_use_db(mode: str) -> bool:
    return mode in {"db", "both"}


def _should_use_files(mode: str) -> bool:
    return mode in {"files", "both"}


def _load_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logging.exception("planning_load_json_failed", extra={"path": str(path)})
        return None


class JobManager:
    def __init__(self, workers: int = 1, db_path: str | None = None):
        self.workers = max(1, workers)
        self.q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self.db_path = db_path

    def start(self):
        if self._threads:
            return
        self._stop.clear()
        for i in range(self.workers):
            t = threading.Thread(
                target=self._run_loop, name=f"job-worker-{i}", daemon=True
            )
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 2.0):
        self._stop.set()
        try:
            while not self.q.empty():
                try:
                    self.q.get_nowait()
                except Exception:
                    break
        except Exception:
            pass
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()

    def submit_simulation(self, payload: Dict[str, Any]) -> str:
        if not self._threads:
            self.start()
        job_id = uuid4().hex
        now = int(time.time() * 1000)
        db.create_job(
            job_id, "simulation", "queued", now, json.dumps(payload, ensure_ascii=False)
        )
        self.q.put({"job_id": job_id, "type": "simulation"})
        try:
            JOBS_ENQUEUED.labels(type="simulation").inc()
        except Exception:
            pass
        return job_id

    def _run_loop(self):
        if self.db_path:
            os.environ["SCPLN_DB"] = self.db_path
        while not self._stop.is_set():
            try:
                job = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            job_id = job.get("job_id")
            jtype = job.get("type")
            # Skip if job is not in queued state anymore (e.g., canceled)
            row = db.get_job(job_id)
            if not row or row.get("status") != "queued":
                continue
            if jtype == "simulation":
                self._run_simulation(job_id)
            elif jtype == "aggregate":
                self._run_aggregate(job_id)
            elif jtype == "planning":
                self._run_planning(job_id)
            else:
                # unknown type: mark failed
                db.update_job_status(
                    job_id,
                    status="failed",
                    finished_at=int(time.time() * 1000),
                    error="unknown job type",
                )
                try:
                    JOBS_FAILED.labels(type=jtype or "unknown").inc()
                except Exception:
                    pass

    def _run_simulation(self, job_id: str):
        started = int(time.time() * 1000)
        db.update_job_status(job_id, status="running", started_at=started)
        t0 = time.monotonic()
        try:
            rec = db.get_job(job_id)
            payload = json.loads(rec.get("params_json") or "{}") if rec else {}
            # extract optional config/scenario context
            config_id = payload.pop("config_id", None)
            scenario_id = payload.pop("scenario_id", None)
            cfg_json = None
            try:
                if payload:
                    cfg_json = payload
            except Exception:
                cfg_json = None
            # parse model
            sim_input = SimulationInput(**payload)
            sim = SupplyChainSimulator(sim_input)
            results, daily_pl = sim.run()
            try:
                summary = sim.compute_summary()
            except Exception:
                summary = {}
            run_id = uuid4().hex
            # store to registry (same as /simulation)
            REGISTRY.put(
                run_id,
                {
                    "run_id": run_id,
                    "started_at": started,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "schema_version": getattr(sim_input, "schema_version", "1.0"),
                    "summary": summary,
                    "results": results,
                    "daily_profit_loss": daily_pl,
                    "cost_trace": getattr(sim, "cost_trace", []),
                    "config_id": config_id,
                    "scenario_id": scenario_id,
                    "config_json": cfg_json,
                },
            )
            try:
                logging.debug(
                    "config_saved",
                    extra={
                        "event": "config_saved",
                        "route": "/jobs/simulation",
                        "run_id": run_id,
                        "config_id": config_id,
                        "config_json_present": bool(cfg_json),
                    },
                )
            except Exception:
                pass
            finished = int(time.time() * 1000)
            db.update_job_status(
                job_id, status="succeeded", finished_at=finished, run_id=run_id
            )
            try:
                JOBS_COMPLETED.labels(type="simulation").inc()
                JOBS_DURATION.labels(type="simulation").observe(time.monotonic() - t0)
            except Exception:
                pass
        except Exception as e:
            finished = int(time.time() * 1000)
            db.update_job_status(
                job_id, status="failed", finished_at=finished, error=str(e)
            )
            try:
                JOBS_FAILED.labels(type="simulation").inc()
            except Exception:
                pass

    def enqueue_existing(self, job_id: str) -> None:
        row = db.get_job(job_id)
        if not row:
            return
        self.q.put({"job_id": job_id, "type": row.get("type") or "simulation"})

    def submit_aggregate(self, payload: Dict[str, Any]) -> str:
        if not self._threads:
            self.start()
        job_id = uuid4().hex
        now = int(time.time() * 1000)
        db.create_job(
            job_id, "aggregate", "queued", now, json.dumps(payload, ensure_ascii=False)
        )
        self.q.put({"job_id": job_id, "type": "aggregate"})
        try:
            JOBS_ENQUEUED.labels(type="aggregate").inc()
        except Exception:
            pass
        return job_id

    def _run_aggregate(self, job_id: str):
        started = int(time.time() * 1000)
        db.update_job_status(job_id, status="running", started_at=started)
        t0 = time.monotonic()
        try:
            rec = db.get_job(job_id)
            cfg = json.loads(rec.get("params_json") or "{}") if rec else {}
            run_id = cfg.get("run_id")
            dataset = (cfg.get("dataset") or "daily_profit_loss").lower()
            bucket = (cfg.get("bucket") or "week").lower()
            group_keys = cfg.get("group_keys") or []
            sum_fields = cfg.get("sum_fields") or None
            product_level = cfg.get("product_level")
            product_map = cfg.get("product_map") or None
            product_key = cfg.get("product_key") or "item"
            location_level = cfg.get("location_level")
            location_map = cfg.get("location_map") or None
            location_key = cfg.get("location_key") or "node"
            # calendar options
            week_start_offset = int(cfg.get("week_start_offset") or 0)
            month_len = int(cfg.get("month_len") or 30)

            run = REGISTRY.get(run_id) if run_id else None
            if not run:
                raise RuntimeError("run not found")
            rows = []
            if dataset in ("pl", "daily_profit_loss"):
                rows = run.get("daily_profit_loss") or []
            elif dataset == "trace":
                rows = run.get("cost_trace") or []
            elif dataset == "results":
                rows = run.get("results") or []
            else:
                raise RuntimeError("unknown dataset")
            if not isinstance(rows, list):
                rows = []

            # time aggregation if day/date present
            if (
                rows
                and isinstance(rows[0], dict)
                and (
                    ("day" in rows[0]) or ("date" in rows[0]) or (cfg.get("date_field"))
                )
            ):
                agg_time = aggregate_by_time(
                    rows,
                    bucket,
                    day_field="day",
                    sum_fields=sum_fields,
                    group_keys=group_keys,
                    week_start_offset=week_start_offset,
                    month_len=month_len,
                    date_field=cfg.get("date_field"),
                    tz=cfg.get("tz"),
                    calendar_mode=cfg.get("calendar_mode"),
                )
            else:
                agg_time = rows

            # axis rollup if requested
            keep = ["period"] if agg_time and "period" in agg_time[0] else []
            out_rows = (
                rollup_axis(
                    agg_time,
                    product_key=product_key,
                    product_map=(product_map or db.get_product_hierarchy()),
                    product_level=product_level,
                    location_key=location_key,
                    location_map=(location_map or db.get_location_hierarchy()),
                    location_level=location_level,
                    keep_fields=keep,
                    sum_fields=sum_fields,
                )
                if (product_level or location_level)
                else agg_time
            )

            db.set_job_result(job_id, json.dumps(out_rows, ensure_ascii=False))
            finished = int(time.time() * 1000)
            db.update_job_status(job_id, status="succeeded", finished_at=finished)
            try:
                JOBS_COMPLETED.labels(type="aggregate").inc()
                JOBS_DURATION.labels(type="aggregate").observe(time.monotonic() - t0)
            except Exception:
                pass
        except Exception as e:
            finished = int(time.time() * 1000)
            db.update_job_status(
                job_id, status="failed", finished_at=finished, error=str(e)
            )
            try:
                JOBS_FAILED.labels(type="aggregate").inc()
            except Exception:
                pass

    def submit_planning(self, params: Dict[str, Any]) -> str:
        if not self._threads:
            self.start()
        job_id = uuid4().hex
        now = int(time.time() * 1000)
        db.create_job(
            job_id, "planning", "queued", now, json.dumps(params, ensure_ascii=False)
        )
        self.q.put({"job_id": job_id, "type": "planning"})
        try:
            JOBS_ENQUEUED.labels(type="planning").inc()
        except Exception:
            pass
        return job_id

    def _run_planning(self, job_id: str):
        started = int(time.time() * 1000)
        db.update_job_status(job_id, status="running", started_at=started)
        t0 = time.monotonic()
        plan_series_rows: list[Dict[str, Any]] = []
        plan_kpi_rows: list[Dict[str, Any]] = []
        plan_repository = PlanRepository(
            db._conn,
            PLAN_DB_WRITE_LATENCY,
            PLAN_SERIES_ROWS_TOTAL,
            PLAN_DB_LAST_SUCCESS_TIMESTAMP,
            PLAN_DB_CAPACITY_TRIM_TOTAL,
            PLAN_DB_LAST_TRIM_TIMESTAMP,
        )
        try:
            import subprocess

            rec = db.get_job(job_id)
            cfg = json.loads(rec.get("params_json") or "{}") if rec else {}
            base = Path(__file__).resolve().parents[1]
            out_dir = Path(
                cfg.get("out_dir") or (base / "out" / f"job_planning_{job_id}")
            )
            out_dir.mkdir(parents=True, exist_ok=True)

            storage_mode = _storage_mode(cfg.get("storage_mode"))
            use_db = _should_use_db(storage_mode)
            use_files = _should_use_files(storage_mode)

            config_version_id = cfg.get("config_version_id")
            if config_version_id is None:
                raise RuntimeError(
                    "config_version_id is required for integrated planning"
                )
            (
                planning_bundle,
                temp_input_dir,
                artifact_paths,
                canonical_config,
            ) = prepare_canonical_inputs(
                int(config_version_id), out_dir, write_artifacts=True
            )
            input_dir = str(temp_input_dir)
            lightweight = bool(cfg.get("lightweight") or False)
            weeks_raw = cfg.get("weeks")
            if weeks_raw in (None, "", 0):
                weeks = "1" if lightweight else "4"
            else:
                weeks = str(weeks_raw)
            round_mode = cfg.get("round_mode") or "int"
            lt_unit = cfg.get("lt_unit") or "day"
            version_id = cfg.get("version_id") or f"job-{job_id[:8]}"
            cutover_date = cfg.get("cutover_date") or None
            recon_window_days = cfg.get("recon_window_days")
            anchor_policy = cfg.get("anchor_policy") or None
            blend_split_next = cfg.get("blend_split_next")
            blend_weight_mode = cfg.get("blend_weight_mode") or None
            calendar_mode = cfg.get("calendar_mode") or None
            max_adjust_ratio = cfg.get("max_adjust_ratio")
            carryover = cfg.get("carryover") or None
            carryover_split = cfg.get("carryover_split")
            tol_abs = cfg.get("tol_abs")
            tol_rel = cfg.get("tol_rel")
            apply_adjusted_flag = bool(cfg.get("apply_adjusted") or False)
            if lightweight:
                apply_adjusted_flag = False
            env = os.environ.copy()
            env.setdefault("PYTHONPATH", str(base))

            canonical_snapshot_path = artifact_paths.get("canonical_snapshot.json")
            planning_inputs_path = artifact_paths.get("planning_inputs.json")

            def runpy(args: list[str]):
                subprocess.run(
                    [sys.executable, *args], cwd=str(base), env=env, check=True
                )

            runpy(
                [
                    "scripts/plan_aggregate.py",
                    "-i",
                    input_dir,
                    "-o",
                    str(out_dir / "aggregate.json"),
                ]
            )
            runpy(
                [
                    "scripts/allocate.py",
                    "-i",
                    str(out_dir / "aggregate.json"),
                    "-I",
                    input_dir,
                    "-o",
                    str(out_dir / "sku_week.json"),
                    "--weeks",
                    weeks,
                    "--round",
                    round_mode,
                ]
            )
            if not lightweight:
                runpy(
                    [
                        "scripts/mrp.py",
                        "-i",
                        str(out_dir / "sku_week.json"),
                        "-I",
                        input_dir,
                        "-o",
                        str(out_dir / "mrp.json"),
                        "--lt-unit",
                        lt_unit,
                        "--weeks",
                        weeks,
                    ]
                )
                args_recon = [
                    "scripts/reconcile.py",
                    "-i",
                    str(out_dir / "sku_week.json"),
                    str(out_dir / "mrp.json"),
                    "-I",
                    input_dir,
                    "-o",
                    str(out_dir / "plan_final.json"),
                    "--weeks",
                    weeks,
                ]
                if cutover_date:
                    args_recon += ["--cutover-date", str(cutover_date)]
                if recon_window_days is not None:
                    args_recon += ["--recon-window-days", str(recon_window_days)]
                if anchor_policy:
                    args_recon += ["--anchor-policy", str(anchor_policy)]
                if blend_split_next is not None:
                    args_recon += ["--blend-split-next", str(blend_split_next)]
                if blend_weight_mode:
                    args_recon += ["--blend-weight-mode", str(blend_weight_mode)]
                runpy(args_recon)
                # reconcile-levels (AGG↔DET 差分ログ)
                args_rl = [
                    "scripts/reconcile_levels.py",
                    "-i",
                    str(out_dir / "aggregate.json"),
                    str(out_dir / "sku_week.json"),
                    "-o",
                    str(out_dir / "reconciliation_log.json"),
                    "--version",
                    version_id,
                    "--tol-abs",
                    "1e-6",
                    "--tol-rel",
                    "1e-6",
                ]
                if cutover_date:
                    args_rl += ["--cutover-date", str(cutover_date)]
                if recon_window_days is not None:
                    args_rl += ["--recon-window-days", str(recon_window_days)]
                if anchor_policy:
                    args_rl += ["--anchor-policy", str(anchor_policy)]
                runpy(args_rl)
                runpy(
                    [
                        "scripts/report.py",
                        "-i",
                        str(out_dir / "plan_final.json"),
                        "-I",
                        input_dir,
                        "-o",
                        str(out_dir / "report.csv"),
                    ]
                )
            if canonical_config is not None and use_files:
                artifacts = {
                    "canonical_snapshot.json": canonical_snapshot_path,
                    "planning_inputs.json": planning_inputs_path,
                    "aggregate.json": out_dir / "aggregate.json",
                    "sku_week.json": out_dir / "sku_week.json",
                    "mrp.json": out_dir / "mrp.json",
                    "plan_final.json": out_dir / "plan_final.json",
                }
                for name, path in artifacts.items():
                    if not path or not path.exists():
                        continue
                    db.upsert_plan_artifact(
                        version_id,
                        name,
                        path.read_text(encoding="utf-8"),
                    )

            try:
                aggregate_obj = _load_json(out_dir / "aggregate.json")
                detail_obj = _load_json(out_dir / "sku_week.json")
                plan_series_rows = build_plan_series(
                    version_id,
                    aggregate=aggregate_obj,
                    detail=detail_obj,
                )
                plan_kpi_rows = build_plan_kpis_from_aggregate(
                    version_id, aggregate_obj
                )
            except Exception:
                logging.exception(
                    "planning_plan_repository_build_failed",
                    extra={"job_id": job_id, "version_id": version_id},
                )

            # optional: anchor adjust and adjusted recalculation
            if not lightweight and anchor_policy and cutover_date:
                args_anchor = [
                    "scripts/anchor_adjust.py",
                    "-i",
                    str(out_dir / "aggregate.json"),
                    str(out_dir / "sku_week.json"),
                    "-o",
                    str(out_dir / "sku_week_adjusted.json"),
                    "--cutover-date",
                    str(cutover_date),
                    "--anchor-policy",
                    str(anchor_policy),
                ]
                if recon_window_days is not None:
                    args_anchor += ["--recon-window-days", str(recon_window_days)]
                if calendar_mode:
                    args_anchor += ["--calendar-mode", str(calendar_mode)]
                if max_adjust_ratio is not None:
                    args_anchor += ["--max-adjust-ratio", str(max_adjust_ratio)]
                if carryover:
                    args_anchor += ["--carryover", str(carryover)]
                if tol_abs is not None:
                    args_anchor += ["--tol-abs", str(tol_abs)]
                if tol_rel is not None:
                    args_anchor += ["--tol-rel", str(tol_rel)]
                if carryover_split is not None:
                    args_anchor += ["--carryover-split", str(carryover_split)]
                runpy(args_anchor)

                args_rl_adj = [
                    "scripts/reconcile_levels.py",
                    "-i",
                    str(out_dir / "aggregate.json"),
                    str(out_dir / "sku_week_adjusted.json"),
                    "-o",
                    str(out_dir / "reconciliation_log_adjusted.json"),
                    "--version",
                    f"{version_id}-adjusted",
                    "--tol-abs",
                    "1e-6",
                    "--tol-rel",
                    "1e-6",
                ]
                if cutover_date:
                    args_rl_adj += ["--cutover-date", str(cutover_date)]
                if recon_window_days is not None:
                    args_rl_adj += ["--recon-window-days", str(recon_window_days)]
                if anchor_policy:
                    args_rl_adj += ["--anchor-policy", str(anchor_policy)]
                runpy(args_rl_adj)

                if apply_adjusted_flag:
                    runpy(
                        [
                            "scripts/mrp.py",
                            "-i",
                            str(out_dir / "sku_week_adjusted.json"),
                            "-I",
                            input_dir,
                            "-o",
                            str(out_dir / "mrp_adjusted.json"),
                            "--lt-unit",
                            lt_unit,
                            "--weeks",
                            weeks,
                        ]
                    )
                    args_recon_adj = [
                        "scripts/reconcile.py",
                        "-i",
                        str(out_dir / "sku_week_adjusted.json"),
                        str(out_dir / "mrp_adjusted.json"),
                        "-I",
                        input_dir,
                        "-o",
                        str(out_dir / "plan_final_adjusted.json"),
                        "--weeks",
                        weeks,
                    ]
                    if cutover_date:
                        args_recon_adj += ["--cutover-date", str(cutover_date)]
                    if recon_window_days is not None:
                        args_recon_adj += [
                            "--recon-window-days",
                            str(recon_window_days),
                        ]
                    if anchor_policy:
                        args_recon_adj += ["--anchor-policy", str(anchor_policy)]
                    if blend_split_next is not None:
                        args_recon_adj += ["--blend-split-next", str(blend_split_next)]
                    if blend_weight_mode:
                        args_recon_adj += [
                            "--blend-weight-mode",
                            str(blend_weight_mode),
                        ]
                    runpy(args_recon_adj)
                    runpy(
                        [
                            "scripts/report.py",
                            "-i",
                            str(out_dir / "plan_final_adjusted.json"),
                            "-I",
                            input_dir,
                            "-o",
                            str(out_dir / "report_adjusted.csv"),
                        ]
                    )

            # persist to plan DB (version + artifacts)
            try:
                db.create_plan_version(
                    version_id,
                    base_scenario_id=cfg.get("base_scenario_id"),
                    status="active",
                    cutover_date=cutover_date,
                    recon_window_days=recon_window_days,
                    objective=cfg.get("objective"),
                    note=cfg.get("note"),
                    config_version_id=config_version_id,
                )

                def _read(p: Path) -> str | None:
                    try:
                        return p.read_text(encoding="utf-8") if p.exists() else None
                    except Exception:
                        return None

                if use_files:
                    for name in (
                        "aggregate.json",
                        "sku_week.json",
                        "mrp.json",
                        "plan_final.json",
                        "reconciliation_log.json",
                        "sku_week_adjusted.json",
                        "mrp_adjusted.json",
                        "plan_final_adjusted.json",
                        "reconciliation_log_adjusted.json",
                    ):
                        t = _read(out_dir / name)
                        if t is not None:
                            db.upsert_plan_artifact(version_id, name, t)
                    for name, path in artifact_paths.items():
                        t = _read(path)
                        if t is not None:
                            db.upsert_plan_artifact(version_id, name, t)
                    # source linkage (optional)
                    src_run = cfg.get("source_run_id")
                    if src_run:
                        try:
                            db.upsert_plan_artifact(
                                version_id,
                                "source.json",
                                json.dumps(
                                    {"source_run_id": str(src_run)}, ensure_ascii=False
                                ),
                            )
                        except Exception:
                            pass
            except Exception:
                # DBへの保存に失敗してもジョブ自体は継続
                logging.exception(
                    "planning_job_persist_failed",
                    extra={"job_id": job_id, "version_id": version_id},
                )

            recorded_run_id: Optional[str] = None
            if canonical_config is not None:
                scenario_id: Optional[int] = None
                scenario_raw = cfg.get("base_scenario_id")
                try:
                    if scenario_raw not in (None, ""):
                        scenario_id = int(scenario_raw)
                except (TypeError, ValueError):
                    scenario_id = None
                recorded_run_id = record_canonical_run(
                    canonical_config,
                    config_version_id=config_version_id,
                    scenario_id=scenario_id,
                    plan_version_id=version_id,
                    plan_job_id=job_id,
                )

            file_list = [
                "aggregate.json",
                "sku_week.json",
                "mrp.json",
                "plan_final.json",
                "reconciliation_log.json",
                *(
                    ["sku_week_adjusted.json", "reconciliation_log_adjusted.json"]
                    if (anchor_policy and cutover_date)
                    else []
                ),
                *(
                    [
                        "mrp_adjusted.json",
                        "plan_final_adjusted.json",
                        "report_adjusted.csv",
                    ]
                    if (anchor_policy and cutover_date and apply_adjusted_flag)
                    else []
                ),
                "report.csv",
            ]
            if config_version_id is not None and use_files:
                file_list.extend(["canonical_snapshot.json", "planning_inputs.json"])
            if not use_files:
                file_list = []
            else:
                file_list = [name for name in file_list if (out_dir / name).exists()]
            result = {
                "out_dir": str(out_dir.relative_to(base)),
                "files": file_list,
                "version_id": version_id,
                "storage_mode": storage_mode,
            }
            if config_version_id is not None:
                result["config_version_id"] = config_version_id
            if recorded_run_id is not None:
                result["run_id"] = recorded_run_id
            db.set_job_result(job_id, json.dumps(result, ensure_ascii=False))
            finished = int(time.time() * 1000)
            duration_ms = finished - started

            repository_status = "disabled" if not use_db else "skipped"
            if use_db and (plan_series_rows or plan_kpi_rows):
                try:
                    plan_job_row = {
                        "job_id": job_id,
                        "version_id": version_id,
                        "status": "succeeded",
                        "submitted_at": rec.get("submitted_at") if rec else None,
                        "started_at": rec.get("started_at") if rec else started,
                        "finished_at": finished,
                        "duration_ms": duration_ms,
                        "config_version_id": config_version_id,
                        "scenario_id": cfg.get("base_scenario_id"),
                        "run_id": recorded_run_id,
                        "trigger": cfg.get("trigger"),
                    }
                    plan_repository.write_plan(
                        version_id,
                        series=plan_series_rows,
                        kpis=plan_kpi_rows,
                        job=plan_job_row,
                        storage_mode=storage_mode,
                    )
                    repository_status = "stored"
                    PLAN_DB_WRITE_TOTAL.labels(storage_mode=storage_mode).inc()
                except PlanRepositoryError:
                    logging.exception(
                        "planning_plan_repository_write_failed",
                        extra={"job_id": job_id, "version_id": version_id},
                    )
                    repository_status = "failed"
                    PLAN_DB_WRITE_ERROR_TOTAL.labels(
                        storage_mode=storage_mode, error_type="repository"
                    ).inc()
                except Exception:
                    logging.exception(
                        "planning_plan_repository_unexpected_error",
                        extra={"job_id": job_id, "version_id": version_id},
                    )
                    repository_status = "failed"
                    PLAN_DB_WRITE_ERROR_TOTAL.labels(
                        storage_mode=storage_mode, error_type="unknown"
                    ).inc()

            result["storage"] = {
                "mode": storage_mode,
                "plan_repository": repository_status,
            }

            db.update_job_status(
                job_id,
                status="succeeded",
                finished_at=finished,
                run_id=recorded_run_id,
            )
            try:
                JOBS_COMPLETED.labels(type="planning").inc()
                JOBS_DURATION.labels(type="planning").observe(time.monotonic() - t0)
            except Exception:
                pass
        except Exception as e:
            finished = int(time.time() * 1000)
            db.update_job_status(
                job_id, status="failed", finished_at=finished, error=str(e)
            )
            try:
                JOBS_FAILED.labels(type="planning").inc()
            except Exception:
                pass


def _materialize_planning_inputs(bundle: PlanningDataBundle, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    aggregate = bundle.aggregate_input
    (dest / "aggregate_input.json").write_text(
        aggregate.model_dump_json(indent=2), encoding="utf-8"
    )

    data = aggregate.model_dump()

    _write_csv(
        dest / "demand_family.csv",
        data.get("demand_family"),
        ["family", "period", "demand"],
    )
    _write_csv(
        dest / "capacity.csv",
        data.get("capacity"),
        ["workcenter", "period", "capacity"],
    )
    _write_csv(
        dest / "mix_share.csv", data.get("mix_share"), ["family", "sku", "share"]
    )
    _write_csv(dest / "item.csv", data.get("item_master"), ["item", "lt", "lot", "moq"])
    _write_csv(dest / "inventory.csv", data.get("inventory"), ["item", "loc", "qty"])
    _write_csv(dest / "open_po.csv", data.get("open_po"), ["item", "due", "qty"])

    if bundle.period_cost:
        _write_csv(dest / "period_cost.csv", bundle.period_cost, ["period", "cost"])
    if bundle.period_score:
        _write_csv(dest / "period_score.csv", bundle.period_score, ["period", "score"])


def _write_csv(path: Path, rows: Optional[list], columns: list[str]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            if not isinstance(row, dict):
                row = dict(row)
            writer.writerow({col: row.get(col) for col in columns})


def prepare_canonical_inputs(
    config_version_id: int,
    out_dir: Path,
    *,
    write_artifacts: bool = False,
) -> Tuple[PlanningDataBundle, Path, Dict[str, Path], CanonicalConfig]:
    logging.info(f"DEBUG: prepare_canonical_inputs called for config_version_id: {config_version_id}")
    try:
        logging.info(f"DEBUG: Loading canonical config from DB for config_version_id: {config_version_id}")
        canonical_config, validation = load_canonical_config_from_db(
            config_version_id, validate=True
        )
        logging.info(f"DEBUG: Canonical config loaded. Validation has errors: {validation.has_errors}")
    except CanonicalConfigNotFoundError as exc:
        logging.error(f"DEBUG: CanonicalConfigNotFoundError: {exc}")
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        logging.exception(f"DEBUG: Unexpected error during load_canonical_config_from_db for config_version_id: {config_version_id}")
        raise RuntimeError(f"Failed to load canonical config: {exc}") from exc

    if validation and validation.has_errors:
        errors = ", ".join(
            f"{issue.code}:{issue.message}"
            for issue in validation.issues
            if issue.severity == "error"
        )
        logging.error(
            f"Canonical config validation issues: {validation.issues}"
        )  # Add this line
        raise RuntimeError(f"canonical config validation failed: {errors}")

    try:
        logging.info("DEBUG: Building planning inputs from canonical config.")
        planning_bundle = build_planning_inputs(canonical_config)
        logging.info("DEBUG: Planning inputs built.")
    except Exception as exc:
        logging.exception("DEBUG: Unexpected error during build_planning_inputs.")
        raise RuntimeError(f"Failed to build planning inputs: {exc}") from exc

    temp_input_dir = out_dir / "canonical_inputs"
    try:
        logging.info(f"DEBUG: Materializing planning inputs to: {temp_input_dir}")
        _materialize_planning_inputs(planning_bundle, temp_input_dir)
        logging.info("DEBUG: Planning inputs materialized.")
    except Exception as exc:
        logging.exception(f"DEBUG: Unexpected error during _materialize_planning_inputs to {temp_input_dir}.")
        raise RuntimeError(f"Failed to materialize planning inputs: {exc}") from exc

    artifact_paths: Dict[str, Path] = {}
    if write_artifacts:
        canonical_snapshot_path = out_dir / "canonical_snapshot.json"
        canonical_snapshot_path.write_text(
            canonical_config.model_dump_json(indent=2), encoding="utf-8"
        )
        artifact_paths["canonical_snapshot.json"] = canonical_snapshot_path

        planning_inputs_path = out_dir / "planning_inputs.json"
        planning_inputs_path.write_text(
            planning_bundle.aggregate_input.model_dump_json(indent=2),
            encoding="utf-8",
        )
        artifact_paths["planning_inputs.json"] = planning_inputs_path

        if planning_bundle.period_cost:
            period_cost_path = out_dir / "period_cost.json"
            period_cost_path.write_text(
                json.dumps(planning_bundle.period_cost, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            artifact_paths["period_cost.json"] = period_cost_path
        if planning_bundle.period_score:
            period_score_path = out_dir / "period_score.json"
            period_score_path.write_text(
                json.dumps(planning_bundle.period_score, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            artifact_paths["period_score.json"] = period_score_path
        logging.info("DEBUG: Artifacts written.")

    return planning_bundle, temp_input_dir, artifact_paths, canonical_config


# singleton manager (workers will be started on app startup)
JOB_MANAGER = JobManager(workers=JOBS_WORKERS)
