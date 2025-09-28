from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, Optional

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from app.metrics import PLAN_EXPORT_COMPARE, PLAN_EXPORT_CARRYOVER, PLAN_EXPORT_SCHEDULE

from app.api import app
from app import db
from core.config.storage import (
    CanonicalConfigNotFoundError,
)
from app.jobs import prepare_canonical_inputs
from app.run_registry import record_canonical_run
import subprocess
import os


BASE_DIR = Path(__file__).resolve().parents[1]


def _get_param(body: Dict[str, Any], key: str, default: Any = None) -> Any:
    val = body.get(key, default)
    if isinstance(val, str) and val == "":
        return None
    return val


def _run_py(args: list[str]) -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(BASE_DIR))
    subprocess.run(["python3", *args], cwd=str(BASE_DIR), env=env, check=True)


# --- PSI overlay/lock helpers (MVP) ---
def _psi_overlay_key_agg(period: Any, family: Any) -> str:
    return f"agg:period={period},family={family}"


def _psi_overlay_key_det(week: Any, sku: Any) -> str:
    return f"det:week={week},sku={sku}"


def _get_overlay(version_id: str) -> Dict[str, Any]:
    obj = db.get_plan_artifact(version_id, "psi_overrides.json") or {}
    return {
        "aggregate": list(obj.get("aggregate") or []),
        "det": list(obj.get("det") or []),
    }


def _save_overlay(version_id: str, data: Dict[str, Any]) -> None:
    db.upsert_plan_artifact(
        version_id, "psi_overrides.json", json.dumps(data, ensure_ascii=False)
    )


def _get_locks(version_id: str) -> set[str]:
    obj = db.get_plan_artifact(version_id, "psi_locks.json") or {}
    return set(obj.get("locks") or [])


def _save_locks(version_id: str, locks: set[str]) -> None:
    db.upsert_plan_artifact(
        version_id,
        "psi_locks.json",
        json.dumps({"locks": sorted(list(locks))}, ensure_ascii=False),
    )


def _get_weights(version_id: str) -> dict[str, float]:
    obj = db.get_plan_artifact(version_id, "psi_weights.json") or {}
    out: dict[str, float] = {}
    for k, v in (obj.get("weights") or {}).items():
        try:
            out[str(k)] = float(v)
        except Exception:
            pass
    return out


def _save_weights(version_id: str, weights: dict[str, float]) -> None:
    db.upsert_plan_artifact(
        version_id,
        "psi_weights.json",
        json.dumps({"weights": weights}, ensure_ascii=False),
    )


def _apply_overlay(
    level: str, base_rows: list[Dict[str, Any]], overlay_rows: list[Dict[str, Any]]
):
    """Return new list with overlay fields applied by key."""
    out: list[Dict[str, Any]] = []
    if level == "aggregate":
        omap: Dict[str, Dict[str, Any]] = {}
        for r in overlay_rows:
            k = _psi_overlay_key_agg(r.get("period"), r.get("family"))
            omap[k] = r
        for r in base_rows:
            k = _psi_overlay_key_agg(r.get("period"), r.get("family"))
            o = omap.get(k) or {}
            nr = dict(r)
            for fn in ("demand", "supply", "backlog", "inventory"):
                if fn in o and o.get(fn) is not None:
                    nr[fn] = o.get(fn)
            out.append(nr)
    else:
        omap: Dict[str, Dict[str, Any]] = {}
        for r in overlay_rows:
            k = _psi_overlay_key_det(r.get("week"), r.get("sku"))
            omap[k] = r
        for r in base_rows:
            k = _psi_overlay_key_det(r.get("week"), r.get("sku"))
            o = omap.get(k) or {}
            nr = dict(r)
            for fn in (
                "demand",
                "supply_plan",
                "backlog",
                "on_hand_start",
                "on_hand_end",
            ):
                if fn in o and o.get(fn) is not None:
                    nr[fn] = o.get(fn)
            out.append(nr)
    return out


def _week_to_month(week: str | None) -> str | None:
    """Convert ISO week (YYYY-Www) to YYYY-MM (month of Thursday in that ISO week)."""
    if not week or not isinstance(week, str):
        return None
    try:
        if "-W" in week:
            y, w = week.split("-W", 1)
            year = int(y)
            wk = int(w)
            import datetime as _dt

            # Use Thursday (4) so that ISO W01 that starts in Dec maps to Jan
            d = _dt.date.fromisocalendar(year, wk, 4)
            return f"{d.year:04d}-{d.month:02d}"
    except Exception:
        return None
    return None


def _auth_ok(req: Request) -> bool:
    """Optional API-key check. If env API_KEY_VALUE is set, require header X-API-Key to match."""
    key = os.environ.get("API_KEY_VALUE")
    if not key:
        return True
    try:
        val = req.headers.get("X-API-Key")
        return bool(val) and (val == key)
    except Exception:
        return False


def _has_edit(req: Request) -> bool:
    k_edit = os.environ.get("API_KEY_EDIT")
    k_any = os.environ.get("API_KEY_VALUE")
    if not k_edit and not k_any:
        return True
    try:
        val = req.headers.get("X-API-Key")
        return bool(val) and (val == k_edit or val == k_any)
    except Exception:
        return False


def _has_approve(req: Request) -> bool:
    k_app = os.environ.get("API_KEY_APPROVE")
    if k_app:
        try:
            return req.headers.get("X-API-Key") == k_app
        except Exception:
            return False
    # fallback to edit key
    return _has_edit(req)


@app.post("/plans/integrated/run")
def post_plans_integrated_run(body: Dict[str, Any] = Body(...)):
    ts = int(time.time())
    version_id = str(_get_param(body, "version_id") or f"v{ts}-{uuid.uuid4().hex[:8]}")
    out_dir = Path(
        _get_param(body, "out_dir") or (BASE_DIR / "out" / f"api_planning_{ts}")
    )
    weeks = str(_get_param(body, "weeks") or 4)
    round_mode = _get_param(body, "round_mode") or "int"
    lt_unit = _get_param(body, "lt_unit") or "day"
    cutover_date = _get_param(body, "cutover_date")
    recon_window_days = _get_param(body, "recon_window_days")
    anchor_policy = _get_param(body, "anchor_policy")
    blend_split_next = _get_param(body, "blend_split_next")
    blend_weight_mode = _get_param(body, "blend_weight_mode")
    carryover = _get_param(body, "carryover")
    carryover_split = _get_param(body, "carryover_split")
    max_adjust_ratio = _get_param(body, "max_adjust_ratio")
    tol_abs = _get_param(body, "tol_abs")
    tol_rel = _get_param(body, "tol_rel")
    calendar_mode = _get_param(body, "calendar_mode")
    apply_adjusted = bool(_get_param(body, "apply_adjusted") or False)

    out_dir.mkdir(parents=True, exist_ok=True)
    config_version_id = _get_param(body, "config_version_id")
    canonical_config = None
    canonical_snapshot_path: Optional[Path] = None
    planning_inputs_path: Optional[Path] = None

    if config_version_id in (None, ""):
        return JSONResponse(
            status_code=400,
            content={"detail": "config_version_id is required for integrated run"},
        )

    try:
        config_version_id = int(config_version_id)
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"detail": "config_version_id must be integer"},
        )
    try:
        (
            _planning_bundle,
            temp_input_dir,
            artifact_paths,
            canonical_config,
        ) = prepare_canonical_inputs(config_version_id, out_dir, write_artifacts=True)
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except CanonicalConfigNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    input_dir = str(temp_input_dir)
    canonical_snapshot_path = artifact_paths.get("canonical_snapshot.json")
    planning_inputs_path = artifact_paths.get("planning_inputs.json")
    # 1) aggregate
    _run_py(
        [
            "scripts/plan_aggregate.py",
            "-i",
            input_dir,
            "-o",
            str(out_dir / "aggregate.json"),
        ]
    )
    # 2) allocate
    _run_py(
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
    # 3) mrp
    _run_py(
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
    # 4) reconcile
    _run_py(
        [
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
            *(
                ["--recon-window-days", str(recon_window_days)]
                if recon_window_days is not None
                else []
            ),
            *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
            *(
                ["--blend-split-next", str(blend_split_next)]
                if (blend_split_next is not None)
                else []
            ),
            *(
                ["--blend-weight-mode", str(blend_weight_mode)]
                if blend_weight_mode
                else []
            ),
        ]
    )
    # 4.5) reconcile-levels (before)
    _run_py(
        [
            "scripts/reconcile_levels.py",
            "-i",
            str(out_dir / "aggregate.json"),
            str(out_dir / "sku_week.json"),
            "-o",
            str(out_dir / "reconciliation_log.json"),
            "--version",
            version_id,
            *(["--cutover-date", str(cutover_date)] if cutover_date else []),
            *(
                ["--recon-window-days", str(recon_window_days)]
                if recon_window_days is not None
                else []
            ),
            *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
            *(
                ["--tol-abs", str(tol_abs)]
                if tol_abs is not None
                else ["--tol-abs", "1e-6"]
            ),
            *(
                ["--tol-rel", str(tol_rel)]
                if tol_rel is not None
                else ["--tol-rel", "1e-6"]
            ),
        ]
    )
    # optional: anchor/adjusted flow
    if anchor_policy and cutover_date:
        _run_py(
            [
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
                *(
                    ["--recon-window-days", str(recon_window_days)]
                    if recon_window_days is not None
                    else []
                ),
                "--weeks",
                weeks,
                *(["--calendar-mode", str(calendar_mode)] if calendar_mode else []),
                *(["--carryover", str(carryover)] if carryover else []),
                *(
                    ["--carryover-split", str(carryover_split)]
                    if (carryover_split is not None)
                    else []
                ),
                *(
                    ["--max-adjust-ratio", str(max_adjust_ratio)]
                    if (max_adjust_ratio is not None)
                    else []
                ),
                *(["--tol-abs", str(tol_abs)] if (tol_abs is not None) else []),
                *(["--tol-rel", str(tol_rel)] if (tol_rel is not None) else []),
                "-I",
                input_dir,
            ]
        )
        _run_py(
            [
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
                *(
                    ["--recon-window-days", str(recon_window_days)]
                    if recon_window_days is not None
                    else []
                ),
                *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
                *(
                    ["--tol-abs", str(tol_abs)]
                    if tol_abs is not None
                    else ["--tol-abs", "1e-6"]
                ),
                *(
                    ["--tol-rel", str(tol_rel)]
                    if tol_rel is not None
                    else ["--tol-rel", "1e-6"]
                ),
            ]
        )
        if apply_adjusted:
            _run_py(
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
            _run_py(
                [
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
                    *(
                        ["--recon-window-days", str(recon_window_days)]
                        if recon_window_days is not None
                        else []
                    ),
                    *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
                    *(
                        ["--blend-split-next", str(blend_split_next)]
                        if (blend_split_next is not None)
                        else []
                    ),
                    *(
                        ["--blend-weight-mode", str(blend_weight_mode)]
                        if blend_weight_mode
                        else []
                    ),
                ]
            )
    # persist to DB
    db.create_plan_version(
        version_id,
        base_scenario_id=body.get("base_scenario_id"),
        status="active",
        cutover_date=cutover_date,
        recon_window_days=recon_window_days,
        objective=body.get("objective"),
        note=body.get("note"),
        config_version_id=config_version_id,
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
    if canonical_config is not None:
        if canonical_snapshot_path and canonical_snapshot_path.exists():
            db.upsert_plan_artifact(
                version_id,
                "canonical_snapshot.json",
                canonical_snapshot_path.read_text(encoding="utf-8"),
            )
        if planning_inputs_path and planning_inputs_path.exists():
            db.upsert_plan_artifact(
                version_id,
                "planning_inputs.json",
                planning_inputs_path.read_text(encoding="utf-8"),
            )
        if (out_dir / "period_cost.json").exists():
            db.upsert_plan_artifact(
                version_id,
                "period_cost.json",
                (out_dir / "period_cost.json").read_text(encoding="utf-8"),
            )
        if (out_dir / "period_score.json").exists():
            db.upsert_plan_artifact(
                version_id,
                "period_score.json",
                (out_dir / "period_score.json").read_text(encoding="utf-8"),
            )
    # Optional: record source linkage (e.g., created from run)
    try:
        src_run = _get_param(body, "source_run_id")
        if src_run:
            db.upsert_plan_artifact(
                version_id,
                "source.json",
                json.dumps({"source_run_id": str(src_run)}, ensure_ascii=False),
            )
    except Exception:
        pass
    artifacts = [
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
    ]
    if canonical_config is not None:
        for name in (
            "canonical_snapshot.json",
            "planning_inputs.json",
            "period_cost.json",
            "period_score.json",
        ):
            if (out_dir / name).exists():
                artifacts.append(name)
    recorded_run_id: Optional[str] = None
    if canonical_config is not None:
        scenario_id: Optional[int] = None
        scenario_raw = body.get("base_scenario_id")
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
        )
    try:
        out_dir_display = str(out_dir.relative_to(BASE_DIR))
    except ValueError:
        out_dir_display = str(out_dir)

    return {
        "version_id": version_id,
        "config_version_id": config_version_id,
        "out_dir": out_dir_display,
        "artifacts": artifacts,
        "run_id": recorded_run_id,
    }


@app.get("/plans/{version_id}/psi")
def get_plan_psi(
    version_id: str,
    level: str = Query("aggregate"),
    q: Optional[str] = Query(None),
    limit: int = Query(200),
    offset: int = Query(0),
):
    level = level if level in ("aggregate", "det") else "aggregate"
    agg = db.get_plan_artifact(version_id, "aggregate.json") or {}
    det = db.get_plan_artifact(version_id, "sku_week.json") or {}
    base_rows: list[Dict[str, Any]]
    if level == "aggregate":
        base_rows = list(agg.get("rows") or [])
        # 統一的に必要なキーのみサブセット
        base_rows = [
            {
                "period": r.get("period"),
                "family": r.get("family"),
                "demand": r.get("demand"),
                "supply": r.get("supply"),
                "backlog": r.get("backlog"),
            }
            for r in base_rows
        ]
    else:
        base_rows = list(det.get("rows") or [])
        base_rows = [
            {
                "week": r.get("week"),
                "sku": r.get("sku"),
                "demand": r.get("demand"),
                "supply_plan": r.get("supply_plan"),
                "backlog": r.get("backlog"),
                "on_hand_start": r.get("on_hand_start"),
                "on_hand_end": r.get("on_hand_end"),
            }
            for r in base_rows
        ]
    overlay = _get_overlay(version_id)
    locks = _get_locks(version_id)
    rows = _apply_overlay(level, base_rows, overlay.get(level) or [])
    # フィルタ
    if q:
        s = (q or "").lower().strip()
        rows = [r for r in rows if s in json.dumps(r, ensure_ascii=False).lower()]
    total = len(rows)
    # ページング
    start = max(0, int(offset))
    end = max(start, start + max(1, int(limit)))
    rows = rows[start:end]
    return {
        "level": level,
        "total": total,
        "rows": rows,
        "locks": sorted(list(locks)),
    }


@app.patch("/plans/{version_id}/psi")
def patch_plan_psi(
    version_id: str, request: Request, body: Dict[str, Any] = Body(default={})
):  # noqa: C901
    if not _has_edit(request):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    level = body.get("level") or "aggregate"
    edits = list(body.get("edits") or [])
    lock_mode = body.get("lock")  # 'lock'|'unlock'|'toggle'|None
    if level not in ("aggregate", "det"):
        return JSONResponse(status_code=400, content={"detail": "invalid level"})
    overlay = _get_overlay(version_id)
    locks = _get_locks(version_id)
    # index overlay by key
    if level == "aggregate":

        def mk(row):
            return _psi_overlay_key_agg(row.get("period"), row.get("family"))

    else:

        def mk(row):
            return _psi_overlay_key_det(row.get("week"), row.get("sku"))

    omap: Dict[str, Dict[str, Any]] = {}
    for r in overlay.get(level) or []:
        omap[mk(r)] = dict(r)
    updated = 0
    skipped: list[str] = []
    affected_keys: set[str] = set()
    # 監査ログの準備
    import time as _time

    audit = db.get_plan_artifact(version_id, "psi_audit.json") or {"events": []}
    events = list(audit.get("events") or [])
    distribute = body.get("distribute") or {}
    weight_mode = str(distribute.get("weight_mode") or "current")
    round_map = distribute.get("round") or {}

    def _round_value(val: float, cfg: Dict[str, Any] | None) -> float:
        if not cfg:
            return val
        try:
            step = float(cfg.get("step") or 0)
            mode = str(cfg.get("mode") or "nearest")
            if step and step > 0:
                q = val / step
                if mode == "floor":
                    from math import floor

                    return floor(q) * step
                if mode == "ceil":
                    from math import ceil

                    return ceil(q) * step
                # nearest
                from math import floor

                return round(q) * step
        except Exception:
            return val
        return val

    for e in edits:
        key = mk(e.get("key") or {})
        if not key:
            continue
        affected_keys.add(key)
        # ロック判定（行ロックのみMVP）
        if key in locks:
            skipped.append(key)
            continue
        row = omap.get(key) or {}
        # key項目を保持
        for k in ("period", "family", "week", "sku"):
            if k in (e.get("key") or {}):
                row[k] = (e.get("key") or {}).get(k)
        fields: Dict[str, Any] = dict(e.get("fields") or {})
        for fn, val in fields.items():
            if val is None:
                # None指定でその上書きを削除
                if fn in row:
                    row.pop(fn, None)
            else:
                try:
                    row[fn] = float(val)
                except Exception:
                    row[fn] = val
        omap[key] = row
        updated += 1
        # 監査イベント追加
        events.append(
            {
                "ts": int(_time.time() * 1000),
                "level": level,
                "key": e.get("key") or {},
                "fields": fields,
                "lock": None,
            }
        )
    # rebuild overlay list
    new_rows: list[Dict[str, Any]] = []
    for v in omap.values():
        # キー以外が空なら除外
        payload = {k: v.get(k) for k in v.keys()}
        new_rows.append(payload)
    overlay[level] = new_rows
    _save_overlay(version_id, overlay)
    # lock operation
    explicit_lock_keys = set()
    for lk in list(body.get("lock_keys") or []):
        try:
            explicit_lock_keys.add(str(lk))
        except Exception:
            pass
    if lock_mode in ("lock", "unlock", "toggle") and (
        affected_keys or explicit_lock_keys
    ):
        keys_to_apply = set(affected_keys) | set(explicit_lock_keys)
        for k in keys_to_apply:
            if lock_mode == "lock":
                locks.add(k)
            elif lock_mode == "unlock":
                if k in locks:
                    locks.discard(k)
            else:  # toggle
                if k in locks:
                    locks.discard(k)
                else:
                    locks.add(k)
        _save_locks(version_id, locks)
        # 監査イベント（ロック）
        events.append(
            {
                "ts": int(_time.time() * 1000),
                "level": level,
                "keys": sorted(list(keys_to_apply)),
                "fields": {},
                "lock": lock_mode,
            }
        )
    # 自動集計（Detail→Aggregate, 編集対象のみロールアップ）
    try:
        if level == "det" and updated > 0 and not body.get("no_auto"):
            agg_base = db.get_plan_artifact(version_id, "aggregate.json") or {}
            agg_rows = list(agg_base.get("rows") or [])
            if agg_rows:
                det_base = db.get_plan_artifact(version_id, "sku_week.json") or {}
                det_rows = list(det_base.get("rows") or [])
                if det_rows:
                    overlay_full = _get_overlay(version_id)
                    det_rows_applied = _apply_overlay(
                        "det", det_rows, overlay_full.get("det") or []
                    )
                    agg_overlay_rows = overlay_full.get("aggregate") or []
                    agg_key_candidates: set[tuple[str, str]] = set()
                    for row in agg_rows + agg_overlay_rows:
                        per = row.get("period")
                        fam = row.get("family")
                        if per is None or fam is None:
                            continue
                        agg_key_candidates.add((str(per), str(fam)))
                    if agg_key_candidates:
                        det_to_agg: Dict[str, tuple[str, str]] = {}
                        for row in det_rows_applied:
                            fam = row.get("family")
                            if fam is None:
                                continue
                            fam_s = str(fam)
                            candidates: list[str] = []
                            per = row.get("period")
                            if per is not None:
                                candidates.append(str(per))
                            wk = row.get("week")
                            if wk:
                                wk_s = str(wk)
                                candidates.append(wk_s)
                                m = _week_to_month(wk_s)
                                if m:
                                    candidates.append(m)
                            seen: set[str] = set()
                            for cand in candidates:
                                if cand in seen:
                                    continue
                                seen.add(cand)
                                key = (cand, fam_s)
                                if key in agg_key_candidates:
                                    det_key = _psi_overlay_key_det(
                                        row.get("week"), row.get("sku")
                                    )
                                    if det_key:
                                        det_to_agg[det_key] = key
                                    break
                        if det_to_agg:
                            target_aggs: set[tuple[str, str]] = set()
                            for e in edits:
                                key_d = e.get("key") or {}
                                det_key = _psi_overlay_key_det(
                                    key_d.get("week"), key_d.get("sku")
                                )
                                if det_key and det_key in det_to_agg:
                                    target_aggs.add(det_to_agg[det_key])
                            if target_aggs:
                                agg_sums: Dict[tuple[str, str], Dict[str, float]] = (
                                    defaultdict(dict)
                                )
                                rollup_map = {
                                    "demand": ("demand",),
                                    "supply": ("supply_plan", "supply"),
                                    "backlog": ("backlog",),
                                }
                                for row in det_rows_applied:
                                    det_key = _psi_overlay_key_det(
                                        row.get("week"), row.get("sku")
                                    )
                                    if not det_key:
                                        continue
                                    agg_key = det_to_agg.get(det_key)
                                    if not agg_key or agg_key not in target_aggs:
                                        continue
                                    for agg_field, src_fields in rollup_map.items():
                                        val = None
                                        for src in src_fields:
                                            if row.get(src) is not None:
                                                val = row.get(src)
                                                break
                                        if val is None:
                                            continue
                                        try:
                                            cur = agg_sums[agg_key].get(agg_field, 0.0)
                                            agg_sums[agg_key][agg_field] = cur + float(
                                                val
                                            )
                                        except Exception:
                                            continue
                                if agg_sums:
                                    locks = _get_locks(version_id)
                                    agg_overlay_map: Dict[str, Dict[str, Any]] = {}
                                    for row in agg_overlay_rows:
                                        key = _psi_overlay_key_agg(
                                            row.get("period"), row.get("family")
                                        )
                                        if key:
                                            agg_overlay_map[key] = dict(row)
                                    for (period, family), fields in agg_sums.items():
                                        krow = _psi_overlay_key_agg(period, family)
                                        if not krow or krow in locks:
                                            continue
                                        row = agg_overlay_map.get(krow) or {
                                            "period": period,
                                            "family": family,
                                        }
                                        updated_any = False
                                        for agg_field, total in fields.items():
                                            kcell = f"{krow}:field={agg_field}"
                                            if kcell in locks:
                                                continue
                                            row[agg_field] = total
                                            updated_any = True
                                        if updated_any:
                                            agg_overlay_map[krow] = row
                                    if agg_overlay_map:
                                        overlay_full["aggregate"] = list(
                                            agg_overlay_map.values()
                                        )
                                        _save_overlay(version_id, overlay_full)
    except Exception:
        pass
    # 自動分配（Aggregate→Detail, 比例配分・セル/行ロック尊重）
    try:
        if level == "aggregate" and updated > 0 and not body.get("no_auto"):
            # 調整対象フィールドのマッピング: agg -> det
            field_map = {
                "demand": "demand",
                "supply": "supply_plan",
                "backlog": "backlog",
            }
            # base det rows
            det = db.get_plan_artifact(version_id, "sku_week.json") or {}
            det_rows = list(det.get("rows") or [])
            # current det overlay map
            det_overlay = _get_overlay(version_id).get("det") or []
            det_map: Dict[str, Dict[str, Any]] = {}
            for r in det_overlay:
                k = _psi_overlay_key_det(r.get("week"), r.get("sku"))
                det_map[k] = dict(r)
            # locks (row/cell)
            locks = _get_locks(version_id)
            # rebuild aggregate overlay index
            agg_overlay = _get_overlay(version_id).get("aggregate") or []
            agg_idx: Dict[tuple, Dict[str, Any]] = {}
            for r in agg_overlay:
                agg_idx[(r.get("period"), r.get("family"))] = r
            # For each affected key, distribute edited fields
            for e in edits:
                keyd = e.get("key") or {}
                per = keyd.get("period")
                fam = keyd.get("family")
                if not per or not fam:
                    continue
                # target values (only fields explicitly in request)
                targets: Dict[str, float] = {}
                for fn_a, fn_d in field_map.items():
                    if fn_a in (e.get("fields") or {}):
                        try:
                            targets[fn_d] = float((e.get("fields") or {}).get(fn_a))
                        except Exception:
                            pass
                if not targets:
                    continue
                # pick matching det rows
                # 条件: family一致 かつ 次のいずれか
                #   - det.period が per と一致（ISO週キー同士の一致）
                #   - det.week が per と一致（aggregate側がISO週キーをperiodに持つ場合）
                #   - _week_to_month(det.week) が per と一致（月キーとISO週の対応）
                idxs = []
                for r in det_rows:
                    if r.get("family") != fam:
                        continue
                    per_det = (
                        str(r.get("period")) if r.get("period") is not None else None
                    )
                    wk_det = str(r.get("week")) if r.get("week") is not None else None
                    if (
                        (per_det is not None and per_det == per)
                        or (wk_det is not None and wk_det == per)
                        or (wk_det is not None and _week_to_month(wk_det) == per)
                    ):
                        idxs.append(r)
                if not idxs:
                    continue
                # current totals
                cur_tot: Dict[str, float] = {}
                for fn_d in targets.keys():
                    s = 0.0
                    for r in idxs:
                        v = r.get(fn_d)
                        try:
                            s += float(v or 0)
                        except Exception:
                            pass
                    cur_tot[fn_d] = s
                # distribute per field
                for fn_d, tgt in targets.items():
                    cur = cur_tot.get(fn_d, 0.0)
                    # choose weights
                    base_vals = []
                    if weight_mode == "equal" or (
                        cur <= 0 and tgt is not None and weight_mode == "current"
                    ):
                        base_vals = [1.0] * len(idxs)
                    else:
                        if weight_mode == "weights":
                            wm = _get_weights(version_id)
                            for r in idxs:
                                k = _psi_overlay_key_det(r.get("week"), r.get("sku"))
                                base_vals.append(float(wm.get(k, 0.0)))
                            if sum(base_vals) <= 0:
                                # fallback to current field
                                base_vals = []
                                for r in idxs:
                                    try:
                                        base_vals.append(float(r.get(fn_d) or 0.0))
                                    except Exception:
                                        base_vals.append(0.0)
                        else:
                            src_field = (
                                fn_d
                                if weight_mode in ("current", fn_d)
                                else weight_mode
                            )
                            for r in idxs:
                                try:
                                    base_vals.append(float(r.get(src_field) or 0.0))
                                except Exception:
                                    base_vals.append(0.0)
                    total_base = sum(base_vals) or 1.0
                    # compute new values vector
                    new_vals = [tgt * (bv / total_base) for bv in base_vals]
                    # honor locks: skip locked rows/cells, re-normalize to unlocked
                    unlocked_idx = []
                    for i, r in enumerate(idxs):
                        krow = _psi_overlay_key_det(r.get("week"), r.get("sku"))
                        kcell = f"{krow}:field={fn_d}"
                        if (krow in locks) or (kcell in locks):
                            continue
                        unlocked_idx.append(i)
                    if not unlocked_idx:
                        continue
                    sum_unlocked = sum(new_vals[i] for i in unlocked_idx) or 1.0
                    scale = (tgt or 0.0) / sum_unlocked
                    for i in unlocked_idx:
                        r = idxs[i]
                        k = _psi_overlay_key_det(r.get("week"), r.get("sku"))
                        row = det_map.get(k) or {
                            "week": r.get("week"),
                            "sku": r.get("sku"),
                        }
                        row[fn_d] = new_vals[i] * scale
                        det_map[k] = row
            # save det overlay (with optional rounding)
            det_rows_new = list(det_map.values())
            # apply rounding per field if configured
            if isinstance(round_map, dict) and det_rows_new:
                for r in det_rows_new:
                    for f, cfg in round_map.items():
                        if f in r and r.get(f) is not None:
                            try:
                                r[f] = _round_value(float(r.get(f)), cfg)
                            except Exception:
                                pass
            ov = _get_overlay(version_id)
            ov["det"] = det_rows_new
            _save_overlay(version_id, ov)
    except Exception:
        pass
    # 監査保存
    try:
        db.upsert_plan_artifact(
            version_id,
            "psi_audit.json",
            json.dumps({"events": events[-10000:]}, ensure_ascii=False),
        )
    except Exception:
        pass
    return {"updated": updated, "skipped": skipped, "locked": sorted(list(locks))}


@app.post("/plans/{version_id}/psi/reconcile")
def post_plan_psi_reconcile(
    version_id: str, request: Request, body: Dict[str, Any] = Body(default={})
):  # noqa: C901
    if not _has_edit(request):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    ver = db.get_plan_version(version_id)
    config_version_id = None
    if ver:
        config_version_id = ver.get("config_version_id")
    # 合成: aggregate/sku_week にオーバレイを適用して一時出力 → reconcile_levels を実行
    agg = db.get_plan_artifact(version_id, "aggregate.json") or {}
    det = db.get_plan_artifact(version_id, "sku_week.json") or {}
    overlay = _get_overlay(version_id)
    agg_rows = list(agg.get("rows") or [])
    det_rows = list(det.get("rows") or [])
    agg_rows2 = _apply_overlay("aggregate", agg_rows, overlay.get("aggregate") or [])
    det_rows2 = _apply_overlay("det", det_rows, overlay.get("det") or [])
    out_dir = Path(BASE_DIR / "out" / f"psi_apply_{version_id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "aggregate.json").write_text(
        json.dumps({"rows": agg_rows2}, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "sku_week.json").write_text(
        json.dumps({"rows": det_rows2}, ensure_ascii=False), encoding="utf-8"
    )
    # 再整合（before の差分ログ）
    _run_py(
        [
            "scripts/reconcile_levels.py",
            "-i",
            str(out_dir / "aggregate.json"),
            str(out_dir / "sku_week.json"),
            "-o",
            str(out_dir / "reconciliation_log.json"),
            "--version",
            version_id,
            "--tol-abs",
            str(body.get("tol_abs") or "1e-6"),
            "--tol-rel",
            str(body.get("tol_rel") or "1e-6"),
        ]
    )
    # 成果物を更新
    db.upsert_plan_artifact(
        version_id,
        "reconciliation_log.json",
        (out_dir / "reconciliation_log.json").read_text(encoding="utf-8"),
    )
    # オプション: adjusted と MRP再計算
    cutover_date = body.get("cutover_date")
    anchor_policy = body.get("anchor_policy")
    recon_window_days = body.get("recon_window_days")
    calendar_mode = body.get("calendar_mode")
    carryover = body.get("carryover")
    carryover_split = body.get("carryover_split")
    tol_abs = body.get("tol_abs")
    tol_rel = body.get("tol_rel")
    weeks = str(body.get("weeks") or "4")
    lt_unit = body.get("lt_unit") or "day"
    apply_adjusted = bool(body.get("apply_adjusted") or False)
    recalc_mrp = bool(body.get("recalc_mrp") or False)
    if apply_adjusted and anchor_policy and cutover_date:
        if config_version_id is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "plan does not have canonical config version"},
            )
        try:
            (
                _planning_bundle,
                temp_input_dir,
                _artifact_paths,
                _canonical_config,
            ) = prepare_canonical_inputs(
                int(config_version_id), out_dir, write_artifacts=False
            )
        except RuntimeError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        input_dir = str(temp_input_dir)
        _run_py(
            [
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
                *(
                    ["--recon-window-days", str(recon_window_days)]
                    if recon_window_days is not None
                    else []
                ),
                *(["--calendar-mode", str(calendar_mode)] if calendar_mode else []),
                *(["--carryover", str(carryover)] if carryover else []),
                *(
                    ["--carryover-split", str(carryover_split)]
                    if (carryover_split is not None)
                    else []
                ),
                *(["--tol-abs", str(tol_abs)] if (tol_abs is not None) else []),
                *(["--tol-rel", str(tol_rel)] if (tol_rel is not None) else []),
                "-I",
                input_dir,
            ]
        )
        _run_py(
            [
                "scripts/reconcile_levels.py",
                "-i",
                str(out_dir / "aggregate.json"),
                str(out_dir / "sku_week_adjusted.json"),
                "-o",
                str(out_dir / "reconciliation_log_adjusted.json"),
                "--version",
                f"{version_id}-adjusted",
                *(["--cutover-date", str(cutover_date)] if cutover_date else []),
                *(
                    ["--recon-window-days", str(recon_window_days)]
                    if recon_window_days is not None
                    else []
                ),
                *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
                *(
                    ["--tol-abs", str(tol_abs)]
                    if tol_abs is not None
                    else ["--tol-abs", "1e-6"]
                ),
                *(
                    ["--tol-rel", str(tol_rel)]
                    if tol_rel is not None
                    else ["--tol-rel", "1e-6"]
                ),
            ]
        )
        db.upsert_plan_artifact(
            version_id,
            "sku_week_adjusted.json",
            (out_dir / "sku_week_adjusted.json").read_text(encoding="utf-8"),
        )
        db.upsert_plan_artifact(
            version_id,
            "reconciliation_log_adjusted.json",
            (out_dir / "reconciliation_log_adjusted.json").read_text(encoding="utf-8"),
        )
        if recalc_mrp:
            _run_py(
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
            _run_py(
                [
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
                    *(
                        ["--recon-window-days", str(recon_window_days)]
                        if recon_window_days is not None
                        else []
                    ),
                    *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
                ]
            )
            db.upsert_plan_artifact(
                version_id,
                "mrp_adjusted.json",
                (out_dir / "mrp_adjusted.json").read_text(encoding="utf-8"),
            )
            db.upsert_plan_artifact(
                version_id,
                "plan_final_adjusted.json",
                (out_dir / "plan_final_adjusted.json").read_text(encoding="utf-8"),
            )
    # 参考: 必要に応じて executed に遷移（UI側の進行感）
    try:
        db.update_plan_version(version_id, status="executed")
    except Exception:
        pass
    recon = db.get_plan_artifact(version_id, "reconciliation_log.json") or {}
    return {
        "ok": True,
        "updated_artifacts": [
            "reconciliation_log.json",
            *(
                ["reconciliation_log_adjusted.json"]
                if (apply_adjusted and anchor_policy and cutover_date)
                else []
            ),
            *(
                ["mrp_adjusted.json", "plan_final_adjusted.json"]
                if (apply_adjusted and anchor_policy and cutover_date and recalc_mrp)
                else []
            ),
        ],
        "summary": (recon.get("summary") or {}),
    }


@app.get("/plans/{version_id}/psi.csv", response_class=PlainTextResponse)
def get_plan_psi_csv(
    version_id: str,
    level: str = Query("aggregate"),
    q: Optional[str] = Query(None),
    limit: int = Query(10000),
    offset: int = Query(0),
):
    data = get_plan_psi(version_id, level, q, limit, offset)
    rows = data.get("rows") or []
    if data.get("level") == "aggregate":
        header = ["period", "family", "demand", "supply", "backlog"]
    else:
        header = [
            "week",
            "sku",
            "demand",
            "supply_plan",
            "backlog",
            "on_hand_start",
            "on_hand_end",
        ]
    import io
    import csv

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) for k in header})
    return PlainTextResponse(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8"
    )


@app.get("/plans/{version_id}/psi/audit")
def get_plan_psi_audit(
    version_id: str,
    level: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(200),
):
    """PSI編集/ロックの監査ログ（最新順）を返す。"""
    obj = db.get_plan_artifact(version_id, "psi_audit.json") or {"events": []}
    rows: list[dict] = list(obj.get("events") or [])
    # 絞り込み
    if level in ("aggregate", "det"):
        rows = [r for r in rows if (r.get("level") == level)]
    if q:
        s = q.lower().strip()
        rows = [r for r in rows if s in json.dumps(r, ensure_ascii=False).lower()]
    rows = rows[-max(1, int(limit)) :]
    rows.reverse()
    return {"events": rows}


@app.get("/plans/{version_id}/psi/weights")
def get_plan_psi_weights(version_id: str):
    w = _get_weights(version_id)
    # as rows [{key, weight}]
    rows = [{"key": k, "weight": v} for k, v in w.items()]
    return {"rows": rows}


@app.post("/plans/{version_id}/psi/weights")
def post_plan_psi_weights(
    version_id: str, request: Request, body: Dict[str, Any] = Body(default={})
):  # noqa: E501
    if not _auth_ok(request):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    weights: dict[str, float] = {}
    if isinstance(body.get("rows"), list):
        for r in body.get("rows"):
            k = str(r.get("key"))
            try:
                v = float(r.get("weight"))
            except Exception:
                continue
            weights[k] = v
    elif isinstance(body.get("csv"), str):
        import csv
        import io

        txt = body.get("csv")
        f = io.StringIO(txt)
        rd = csv.DictReader(f)
        for r in rd:
            k = r.get("key") or (
                f"det:week={r.get('week')},sku={r.get('sku')}"
                if r.get("week") and r.get("sku")
                else None
            )
            if not k:
                continue
            try:
                v = float(r.get("weight"))
            except Exception:
                continue
            weights[str(k)] = v
    else:
        return JSONResponse(status_code=400, content={"detail": "rows or csv required"})
    _save_weights(version_id, weights)
    return {"ok": True, "count": len(weights)}


@app.post("/plans/{version_id}/psi/submit")
def post_plan_psi_submit(
    version_id: str, request: Request, body: Dict[str, Any] = Body(default={})
):  # noqa: E501
    # だれでも提出可（APIキー設定時は推奨）
    state = db.get_plan_artifact(version_id, "psi_state.json") or {}
    state.update(
        {
            "status": "pending",
            "note": body.get("note"),
            "submitted_at": int(__import__("time").time() * 1000),
        }
    )
    db.upsert_plan_artifact(
        version_id, "psi_state.json", json.dumps(state, ensure_ascii=False)
    )
    # 監査
    audit = db.get_plan_artifact(version_id, "psi_audit.json") or {"events": []}
    ev = list(audit.get("events") or [])
    ev.append(
        {"ts": state.get("submitted_at"), "event": "submit", "note": body.get("note")}
    )
    db.upsert_plan_artifact(
        version_id,
        "psi_audit.json",
        json.dumps({"events": ev[-10000:]}, ensure_ascii=False),
    )
    return {"ok": True, "status": state.get("status")}


@app.post("/plans/{version_id}/psi/approve")
def post_plan_psi_approve(
    version_id: str, request: Request, body: Dict[str, Any] = Body(default={})
):  # noqa: E501
    if not _auth_ok(request):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    state = db.get_plan_artifact(version_id, "psi_state.json") or {}
    now = int(__import__("time").time() * 1000)
    state.update(
        {
            "status": "approved",
            "approved_at": now,
        }
    )
    db.upsert_plan_artifact(
        version_id, "psi_state.json", json.dumps(state, ensure_ascii=False)
    )
    # 自動整合（任意）
    if bool(body.get("auto_reconcile") or False):
        # デフォルトは差分ログのみ
        post_plan_psi_reconcile(version_id, request, body)
    # 監査
    audit = db.get_plan_artifact(version_id, "psi_audit.json") or {"events": []}
    ev = list(audit.get("events") or [])
    ev.append(
        {
            "ts": now,
            "event": "approve",
            "auto_reconcile": bool(body.get("auto_reconcile") or False),
        }
    )
    db.upsert_plan_artifact(
        version_id,
        "psi_audit.json",
        json.dumps({"events": ev[-10000:]}, ensure_ascii=False),
    )
    return {"ok": True, "status": state.get("status")}


@app.get("/plans")
def get_plans(limit: int = 100):
    return {"plans": db.list_plan_versions(limit)}


@app.get("/plans/by_base")
def get_plans_by_base(
    base_scenario_id: int = Query(...),
    limit: int = Query(5),
    sort: str = Query("created_desc"),
):
    rows = db.list_plan_versions_by_base(int(base_scenario_id), max(1, int(limit)))
    # apply sort option
    if sort == "created_asc":
        rows.sort(key=lambda r: r.get("created_at") or 0)
    elif sort == "status":
        rows.sort(
            key=lambda r: (str(r.get("status") or ""), -int(r.get("created_at") or 0)),
            reverse=False,
        )
    # default: created_desc already from DB
    # enrich KPIs (lightweight): capacity/utilization totals from weekly_summary
    enriched = []
    for r in rows:
        ver = r.get("version_id")
        cap_total = adj_total = util_pct = None
        try:
            pf = db.get_plan_artifact(str(ver), "plan_final.json") or {}
            ws = list((pf.get("weekly_summary") or []))
            cap = sum(float(x.get("capacity") or 0) for x in ws)
            adj = sum(float(x.get("adjusted_load") or 0) for x in ws)
            cap_total = cap
            adj_total = adj
            util_pct = (adj / cap * 100.0) if cap else None
        except Exception:
            pass
        enriched.append(
            {
                **r,
                "capacity_total": cap_total,
                "adjusted_total": adj_total,
                "util_pct": util_pct,
            }
        )
    return {"plans": enriched}


@app.get("/plans/{version_id}/summary")
def get_plan_summary(version_id: str):
    ver = db.get_plan_version(version_id)
    if not ver:
        return JSONResponse(status_code=404, content={"detail": "version not found"})
    recon = db.get_plan_artifact(version_id, "reconciliation_log.json") or {}
    recon_adj = (
        db.get_plan_artifact(version_id, "reconciliation_log_adjusted.json") or {}
    )
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
        return JSONResponse(
            status_code=400, content={"detail": "missing aggregate or sku_week"}
        )
    # write to temp out
    out_dir = Path(
        body.get("out_dir") or (BASE_DIR / "out" / f"reconcile_{version_id}")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "aggregate.json").write_text(
        json.dumps(agg, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "sku_week.json").write_text(
        json.dumps(det, ensure_ascii=False), encoding="utf-8"
    )
    cutover_date = body.get("cutover_date") or ver.get("cutover_date")
    recon_window_days = body.get("recon_window_days") or ver.get("recon_window_days")
    anchor_policy = body.get("anchor_policy")
    tol_abs = body.get("tol_abs")
    tol_rel = body.get("tol_rel")
    calendar_mode = body.get("calendar_mode")
    carryover = body.get("carryover")
    carryover_split = body.get("carryover_split")
    config_version_id = ver.get("config_version_id")
    if config_version_id is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "plan does not have canonical config version"},
        )
    try:
        (
            _planning_bundle,
            temp_input_dir,
            _artifact_paths,
            _canonical_config,
        ) = prepare_canonical_inputs(
            int(config_version_id), out_dir, write_artifacts=False
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    input_dir = str(temp_input_dir)

    # before
    _run_py(
        [
            "scripts/reconcile_levels.py",
            "-i",
            str(out_dir / "aggregate.json"),
            str(out_dir / "sku_week.json"),
            "-o",
            str(out_dir / "reconciliation_log.json"),
            "--version",
            version_id,
            *(["--cutover-date", str(cutover_date)] if cutover_date else []),
            *(
                ["--recon-window-days", str(recon_window_days)]
                if recon_window_days is not None
                else []
            ),
            *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
            *(
                ["--tol-abs", str(tol_abs)]
                if tol_abs is not None
                else ["--tol-abs", "1e-6"]
            ),
            *(
                ["--tol-rel", str(tol_rel)]
                if tol_rel is not None
                else ["--tol-rel", "1e-6"]
            ),
        ]
    )
    db.upsert_plan_artifact(
        version_id,
        "reconciliation_log.json",
        (out_dir / "reconciliation_log.json").read_text(encoding="utf-8"),
    )
    # optional: adjusted reconcile
    apply_adjusted = bool(body.get("apply_adjusted") or False)
    if anchor_policy and cutover_date:
        _run_py(
            [
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
                *(
                    ["--recon-window-days", str(recon_window_days)]
                    if recon_window_days is not None
                    else []
                ),
                *(["--calendar-mode", str(calendar_mode)] if calendar_mode else []),
                *(["--carryover", str(carryover)] if carryover else []),
                *(
                    ["--carryover-split", str(carryover_split)]
                    if (carryover_split is not None)
                    else []
                ),
                *(["--tol-abs", str(tol_abs)] if (tol_abs is not None) else []),
                *(["--tol-rel", str(tol_rel)] if (tol_rel is not None) else []),
                "-I",
                input_dir,
            ]
        )
        _run_py(
            [
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
                *(
                    ["--recon-window-days", str(recon_window_days)]
                    if recon_window_days is not None
                    else []
                ),
                *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
                *(
                    ["--tol-abs", str(tol_abs)]
                    if tol_abs is not None
                    else ["--tol-abs", "1e-6"]
                ),
                *(
                    ["--tol-rel", str(tol_rel)]
                    if tol_rel is not None
                    else ["--tol-rel", "1e-6"]
                ),
            ]
        )
        db.upsert_plan_artifact(
            version_id,
            "sku_week_adjusted.json",
            (out_dir / "sku_week_adjusted.json").read_text(encoding="utf-8"),
        )
        db.upsert_plan_artifact(
            version_id,
            "reconciliation_log_adjusted.json",
            (out_dir / "reconciliation_log_adjusted.json").read_text(encoding="utf-8"),
        )
        if apply_adjusted:
            # recompute mrp/reconcile adjusted
            _run_py(
                [
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
                ]
            )
            _run_py(
                [
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
                    *(
                        ["--recon-window-days", str(recon_window_days)]
                        if recon_window_days is not None
                        else []
                    ),
                    *(["--anchor-policy", str(anchor_policy)] if anchor_policy else []),
                ]
            )
            db.upsert_plan_artifact(
                version_id,
                "mrp_adjusted.json",
                (out_dir / "mrp_adjusted.json").read_text(encoding="utf-8"),
            )
            db.upsert_plan_artifact(
                version_id,
                "plan_final_adjusted.json",
                (out_dir / "plan_final_adjusted.json").read_text(encoding="utf-8"),
            )
    # respond with summaries
    recon = db.get_plan_artifact(version_id, "reconciliation_log.json") or {}
    recon_adj = (
        db.get_plan_artifact(version_id, "reconciliation_log_adjusted.json") or {}
    )
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
        xs = [
            abs(float(r.get("rel_demand", 0) or 0)),
            abs(float(r.get("rel_supply", 0) or 0)),
            abs(float(r.get("rel_backlog", 0) or 0)),
        ]
        return max(xs)

    def _absmax(r: Dict[str, Any]) -> float:
        xs = [
            abs(float(r.get("delta_demand", 0) or 0)),
            abs(float(r.get("delta_supply", 0) or 0)),
            abs(float(r.get("delta_backlog", 0) or 0)),
        ]
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
    import io
    import csv

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) for k in header})
    try:
        PLAN_EXPORT_COMPARE.labels(mode=sort).inc()
    except Exception:
        pass
    return PlainTextResponse(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8"
    )


@app.get("/plans/{version_id}/schedule.csv", response_class=PlainTextResponse)
def get_plan_schedule_csv(version_id: str):
    """Export a lightweight planned schedule from mrp.json.
    Columns: week, sku, scheduled_receipts, on_hand_start, on_hand_end.
    """
    mrp = db.get_plan_artifact(version_id, "mrp.json") or {}
    rows = list(mrp.get("rows") or [])
    header = [
        "week",
        "sku",
        "scheduled_receipts",
        "on_hand_start",
        "on_hand_end",
    ]
    import io
    import csv

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    for r in rows:
        w.writerow(
            {
                "week": r.get("week"),
                "sku": r.get("sku"),
                "scheduled_receipts": r.get("scheduled_receipts"),
                "on_hand_start": r.get("on_hand_start"),
                "on_hand_end": r.get("on_hand_end"),
            }
        )
    try:
        PLAN_EXPORT_SCHEDULE.inc()
    except Exception:
        pass
    return PlainTextResponse(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8"
    )


@app.get("/plans/{version_id}/carryover.csv", response_class=PlainTextResponse)
def get_plan_carryover_csv(version_id: str):
    adj = db.get_plan_artifact(version_id, "sku_week_adjusted.json") or {}
    cov = list(adj.get("carryover") or [])
    header = [
        "family",
        "from_period",
        "to_period",
        "delta_demand",
        "delta_supply",
        "delta_backlog",
        "cap_norm",
        "headroom_prev",
        "headroom_next",
        "cap_norm_prev",
        "cap_norm_next",
    ]
    import io
    import csv

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
    try:
        PLAN_EXPORT_CARRYOVER.inc()
    except Exception:
        pass
    return PlainTextResponse(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8"
    )
