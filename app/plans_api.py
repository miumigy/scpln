from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from app.metrics import PLAN_EXPORT_COMPARE, PLAN_EXPORT_CARRYOVER, PLAN_EXPORT_SCHEDULE

from app.api import app
from app import db
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


def _apply_overlay(level: str, base_rows: list[Dict[str, Any]], overlay_rows: list[Dict[str, Any]]):
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


@app.post("/plans/integrated/run")
def post_plans_integrated_run(body: Dict[str, Any] = Body(...)):
    ts = int(time.time())
    version_id = str(_get_param(body, "version_id") or f"v{ts}-{uuid.uuid4().hex[:8]}")
    input_dir = _get_param(body, "input_dir") or "samples/planning"
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
        rows = [
            r
            for r in rows
            if s in json.dumps(r, ensure_ascii=False).lower()
        ]
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
def patch_plan_psi(version_id: str, body: Dict[str, Any] = Body(default={})):  # noqa: C901
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
    if lock_mode in ("lock", "unlock", "toggle") and affected_keys:
        for k in affected_keys:
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
                "keys": sorted(list(affected_keys)),
                "fields": {},
                "lock": lock_mode,
            }
        )
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
def post_plan_psi_reconcile(version_id: str, body: Dict[str, Any] = Body(default={})):  # noqa: C901
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
        input_dir = body.get("input_dir") or "samples/planning"
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
            *(["reconciliation_log_adjusted.json"] if (apply_adjusted and anchor_policy and cutover_date) else []),
            *(["mrp_adjusted.json", "plan_final_adjusted.json"] if (apply_adjusted and anchor_policy and cutover_date and recalc_mrp) else []),
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
    import io, csv
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) for k in header})
    return PlainTextResponse(content=buf.getvalue(), media_type="text/csv; charset=utf-8")


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
    input_dir = body.get("input_dir") or "samples/planning"

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
