from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api import app
from app import db
import subprocess
import os


BASE_DIR = Path(__file__).resolve().parents[1]


def _run_py(args: list[str]) -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(BASE_DIR))
    subprocess.run(["python3", *args], cwd=str(BASE_DIR), env=env, check=True)


@app.post("/plans/integrated/run")
def post_plans_integrated_run(body: Dict[str, Any] = Body(...)):
    ts = int(time.time())
    version_id = str(body.get("version_id") or f"v{ts}-{uuid.uuid4().hex[:8]}")
    input_dir = body.get("input_dir") or "samples/planning"
    out_dir = Path(body.get("out_dir") or (BASE_DIR / "out" / f"api_planning_{ts}"))
    weeks = str(body.get("weeks") or 4)
    round_mode = body.get("round_mode") or "int"
    lt_unit = body.get("lt_unit") or "day"
    cutover_date = body.get("cutover_date")
    recon_window_days = body.get("recon_window_days")
    anchor_policy = body.get("anchor_policy")
    carryover = body.get("carryover")
    carryover_split = body.get("carryover_split")
    max_adjust_ratio = body.get("max_adjust_ratio")
    tol_abs = body.get("tol_abs")
    tol_rel = body.get("tol_rel")
    calendar_mode = body.get("calendar_mode")
    apply_adjusted = bool(body.get("apply_adjusted") or False)

    out_dir.mkdir(parents=True, exist_ok=True)
    # 1) aggregate
    _run_py(["scripts/plan_aggregate.py", "-i", input_dir, "-o", str(out_dir / "aggregate.json")])
    # 2) allocate
    _run_py([
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
    ])
    # 3) mrp
    _run_py([
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
    ])
    # 4) reconcile
    _run_py([
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
        *(["--cutover-date", str(cutover_date)] if cutover_date else []),
        *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
        *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
    ])
    # 4.5) reconcile-levels (before)
    _run_py([
        "scripts/reconcile_levels.py",
        "-i",
        str(out_dir / "aggregate.json"),
        str(out_dir / "sku_week.json"),
        "-o",
        str(out_dir / "reconciliation_log.json"),
        "--version",
        version_id,
        *(["--cutover-date", str(cutover_date)] if cutover_date else []),
        *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
        *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
        *(["--tol-abs", str(tol_abs)] if tol_abs is not None else ["--tol-abs", "1e-6"]),
        *(["--tol-rel", str(tol_rel)] if tol_rel is not None else ["--tol-rel", "1e-6"]),
    ])
    # optional: anchor/adjusted flow
    if anchor_policy and cutover_date:
        _run_py([
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
            *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
            "--weeks",
            weeks,
            *(["--calendar-mode", str(calendar_mode)] if calendar_mode else []),
            *(["--carryover", str(carryover)] if carryover else []),
            *(["--carryover-split", str(carryover_split)] if (carryover_split is not None) else []),
            *(["--max-adjust-ratio", str(max_adjust_ratio)] if (max_adjust_ratio is not None) else []),
            *(["--tol-abs", str(tol_abs)] if (tol_abs is not None) else []),
            *(["--tol-rel", str(tol_rel)] if (tol_rel is not None) else []),
            "-I",
            input_dir,
        ])
        _run_py([
            "scripts/reconcile_levels.py",
            "-i",
            str(out_dir / "aggregate.json"),
            str(out_dir / "sku_week_adjusted.json"),
            "-o",
            str(out_dir / "reconciliation_log_adjusted.json"),
            "--version",
            f"{version_id}-adjusted",
            "--cutover-date",
            str(cutover_date),
            *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
            *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
            *(["--tol-abs", str(tol_abs)] if tol_abs is not None else ["--tol-abs", "1e-6"]),
            *(["--tol-rel", str(tol_rel)] if tol_rel is not None else ["--tol-rel", "1e-6"]),
        ])
        if apply_adjusted:
            _run_py([
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
            ])
            _run_py([
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
                *(["--cutover-date", str(cutover_date)] if cutover_date else []),
                *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
                *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
            ])
    # persist to DB
    db.create_plan_version(
        version_id,
        base_scenario_id=body.get("base_scenario_id"),
        status="active",
        cutover_date=cutover_date,
        recon_window_days=recon_window_days,
        objective=body.get("objective"),
        note=body.get("note"),
    )
    def _load(p: Path) -> Optional[str]:
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None
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
        t = _load(out_dir / name)
        if t is not None:
            db.upsert_plan_artifact(version_id, name, t)
    return {
        "version_id": version_id,
        "out_dir": str(out_dir.relative_to(BASE_DIR)),
        "artifacts": [
            name
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
            )
            if (out_dir / name).exists()
        ],
    }


@app.get("/plans")
def get_plans(limit: int = 100):
    return {"plans": db.list_plan_versions(limit)}


@app.get("/plans/{version_id}/summary")
def get_plan_summary(version_id: str):
    ver = db.get_plan_version(version_id)
    if not ver:
        return JSONResponse(status_code=404, content={"detail": "version not found"})
    recon = db.get_plan_artifact(version_id, "reconciliation_log.json") or {}
    recon_adj = db.get_plan_artifact(version_id, "reconciliation_log_adjusted.json") or {}
    plan_final = db.get_plan_artifact(version_id, "plan_final.json") or {}
    return {
        "version": ver,
        "reconciliation": recon.get("summary"),
        "reconciliation_adjusted": recon_adj.get("summary"),
        "weekly_summary": (plan_final or {}).get("weekly_summary"),
    }


@app.post("/plans/{version_id}/reconcile")
def post_plan_reconcile(
    version_id: str,
    body: Dict[str, Any] = Body(default={}),
):
    ver = db.get_plan_version(version_id)
    if not ver:
        return JSONResponse(status_code=404, content={"detail": "version not found"})
    # Load artifacts
    agg = db.get_plan_artifact(version_id, "aggregate.json")
    det = db.get_plan_artifact(version_id, "sku_week.json")
    if not agg or not det:
        return JSONResponse(status_code=400, content={"detail": "missing aggregate or sku_week"})
    # write to temp out
    out_dir = Path(body.get("out_dir") or (BASE_DIR / "out" / f"reconcile_{version_id}"))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "aggregate.json").write_text(json.dumps(agg, ensure_ascii=False), encoding="utf-8")
    (out_dir / "sku_week.json").write_text(json.dumps(det, ensure_ascii=False), encoding="utf-8")
    cutover_date = body.get("cutover_date") or ver.get("cutover_date")
    recon_window_days = body.get("recon_window_days") or ver.get("recon_window_days")
    anchor_policy = body.get("anchor_policy")
    tol_abs = body.get("tol_abs")
    tol_rel = body.get("tol_rel")
    calendar_mode = body.get("calendar_mode")
    carryover = body.get("carryover")
    carryover_split = body.get("carryover_split")
    input_dir = body.get("input_dir") or "samples/planning"

    # before
    _run_py([
        "scripts/reconcile_levels.py",
        "-i",
        str(out_dir / "aggregate.json"),
        str(out_dir / "sku_week.json"),
        "-o",
        str(out_dir / "reconciliation_log.json"),
        "--version",
        version_id,
        *(["--cutover-date", str(cutover_date)] if cutover_date else []),
        *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
        *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
        *(["--tol-abs", str(tol_abs)] if tol_abs is not None else ["--tol-abs", "1e-6"]),
        *(["--tol-rel", str(tol_rel)] if tol_rel is not None else ["--tol-rel", "1e-6"]),
    ])
    db.upsert_plan_artifact(version_id, "reconciliation_log.json", (out_dir / "reconciliation_log.json").read_text(encoding="utf-8"))
    # optional: adjusted reconcile
    apply_adjusted = bool(body.get("apply_adjusted") or False)
    if anchor_policy and cutover_date:
        _run_py([
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
            *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
            *(["--calendar-mode", str(calendar_mode)] if calendar_mode else []),
            *(["--carryover", str(carryover)] if carryover else []),
            *(["--carryover-split", str(carryover_split)] if (carryover_split is not None) else []),
            *(["--tol-abs", str(tol_abs)] if (tol_abs is not None) else []),
            *(["--tol-rel", str(tol_rel)] if (tol_rel is not None) else []),
            "-I",
            input_dir,
        ])
        _run_py([
            "scripts/reconcile_levels.py",
            "-i",
            str(out_dir / "aggregate.json"),
            str(out_dir / "sku_week_adjusted.json"),
            "-o",
            str(out_dir / "reconciliation_log_adjusted.json"),
            "--version",
            f"{version_id}-adjusted",
            "--cutover-date",
            str(cutover_date),
            *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
            *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
            *(["--tol-abs", str(tol_abs)] if tol_abs is not None else ["--tol-abs", "1e-6"]),
            *(["--tol-rel", str(tol_rel)] if tol_rel is not None else ["--tol-rel", "1e-6"]),
        ])
        db.upsert_plan_artifact(version_id, "sku_week_adjusted.json", (out_dir / "sku_week_adjusted.json").read_text(encoding="utf-8"))
        db.upsert_plan_artifact(version_id, "reconciliation_log_adjusted.json", (out_dir / "reconciliation_log_adjusted.json").read_text(encoding="utf-8"))
        if apply_adjusted:
            # recompute mrp/reconcile adjusted
            _run_py([
                "scripts/mrp.py",
                "-i",
                str(out_dir / "sku_week_adjusted.json"),
                "-I",
                input_dir,
                "-o",
                str(out_dir / "mrp_adjusted.json"),
                "--lt-unit",
                body.get("lt_unit") or "day",
                "--weeks",
                str(body.get("weeks") or 4),
            ])
            _run_py([
                "scripts/reconcile.py",
                "-i",
                str(out_dir / "sku_week_adjusted.json"),
                str(out_dir / "mrp_adjusted.json"),
                "-I",
                input_dir,
                "-o",
                str(out_dir / "plan_final_adjusted.json"),
                "--weeks",
                str(body.get("weeks") or 4),
                *(["--cutover-date", str(cutover_date)] if cutover_date else []),
                *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
                *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
            ])
            db.upsert_plan_artifact(version_id, "mrp_adjusted.json", (out_dir / "mrp_adjusted.json").read_text(encoding="utf-8"))
            db.upsert_plan_artifact(version_id, "plan_final_adjusted.json", (out_dir / "plan_final_adjusted.json").read_text(encoding="utf-8"))
    # respond with summaries
    recon = db.get_plan_artifact(version_id, "reconciliation_log.json") or {}
    recon_adj = db.get_plan_artifact(version_id, "reconciliation_log_adjusted.json") or {}
    return {
        "version_id": version_id,
        "reconciliation": recon.get("summary"),
        "reconciliation_adjusted": recon_adj.get("summary"),
    }


@app.get("/plans/{version_id}/compare")
def get_plan_compare(
    version_id: str,
    violations_only: bool = Query(False),
    sort: str = Query("rel_desc"),
    limit: int = Query(200),
):
    recon = db.get_plan_artifact(version_id, "reconciliation_log.json") or {}
    deltas = list(recon.get("deltas") or [])
    if violations_only:
        deltas = [r for r in deltas if not bool(r.get("ok"))]
    # sort by rel max
    def _relmax(r: Dict[str, Any]) -> float:
        xs = [abs(float(r.get("rel_demand", 0) or 0)), abs(float(r.get("rel_supply", 0) or 0)), abs(float(r.get("rel_backlog", 0) or 0))]
        return max(xs)

    def _absmax(r: Dict[str, Any]) -> float:
        xs = [abs(float(r.get("delta_demand", 0) or 0)), abs(float(r.get("delta_supply", 0) or 0)), abs(float(r.get("delta_backlog", 0) or 0))]
        return max(xs)

    if sort == "rel_desc":
        deltas.sort(key=_relmax, reverse=True)
    elif sort == "rel_asc":
        deltas.sort(key=_relmax)
    elif sort == "abs_desc":
        deltas.sort(key=_absmax, reverse=True)
    elif sort == "abs_asc":
        deltas.sort(key=_absmax)
    return {"version_id": version_id, "rows": deltas[: max(0, int(limit))]}
@app.get("/plans/{version_id}/compare.csv", response_class=PlainTextResponse)
def get_plan_compare_csv(
    version_id: str,
    violations_only: bool = Query(False),
    sort: str = Query("rel_desc"),
    limit: int = Query(1000),
):
    data = get_plan_compare(version_id, violations_only, sort, limit)
    rows = data.get("rows") or []
    header = [
        "family",
        "period",
        "agg_demand",
        "det_demand",
        "delta_demand",
        "rel_demand",
        "ok_demand",
        "agg_supply",
        "det_supply",
        "delta_supply",
        "rel_supply",
        "ok_supply",
        "agg_backlog",
        "det_backlog",
        "delta_backlog",
        "rel_backlog",
        "ok_backlog",
        "ok",
    ]
    import io, csv

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) for k in header})
    return PlainTextResponse(content=buf.getvalue(), media_type="text/csv; charset=utf-8")


@app.get("/plans/{version_id}/carryover.csv", response_class=PlainTextResponse)
def get_plan_carryover_csv(version_id: str):
    adj = db.get_plan_artifact(version_id, "sku_week_adjusted.json") or {}
    cov = list(adj.get("carryover") or [])
    header = ["family", "from_period", "to_period", "delta_demand", "delta_supply", "delta_backlog", "cap_norm", "headroom_prev", "headroom_next", "cap_norm_prev", "cap_norm_next"]
    import io, csv

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    for r in cov:
        m = r.get("metrics") or {}
        w.writerow(
            {
                "family": r.get("family"),
                "from_period": r.get("from_period"),
                "to_period": r.get("to_period"),
                "delta_demand": m.get("demand"),
                "delta_supply": m.get("supply"),
                "delta_backlog": m.get("backlog"),
                "cap_norm": r.get("cap_norm"),
                "headroom_prev": r.get("headroom_prev"),
                "headroom_next": r.get("headroom_next"),
                "cap_norm_prev": r.get("cap_norm_prev"),
                "cap_norm_next": r.get("cap_norm_next"),
            }
        )
    return PlainTextResponse(content=buf.getvalue(), media_type="text/csv; charset=utf-8")
