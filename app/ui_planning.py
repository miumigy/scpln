from __future__ import annotations

from app.api import app
from fastapi import Request, Form, Query, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.jobs import JOB_MANAGER
import os
import json
import subprocess
import time


_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


def _run_py(args: list[str], env: dict | None = None) -> None:
    e = os.environ.copy()
    e.setdefault("PYTHONPATH", str(_BASE_DIR))
    if env:
        e.update(env)
    subprocess.run(["python3", *args], cwd=str(_BASE_DIR), env=e, check=True)


@app.get("/ui/planning", response_class=HTMLResponse)
def ui_planning(request: Request, dir: str | None = Query(None)):
    out = None
    agg = sku = mrp = plan = report = recon = recon_path = None
    plan_adj = report_adj = recon_adj = recon_adj_path = None
    err_msgs: list[str] = []
    if dir:
        out = Path(dir)
        if not out.is_absolute():
            out = _BASE_DIR / out
        # 読み込みは個別に行い、部分的に表示可能にする
        try:
            p = out / "aggregate.json"
            if p.exists():
                agg = json.loads(p.read_text(encoding="utf-8"))
            else:
                err_msgs.append(f"missing: {p}")
        except Exception as e:
            err_msgs.append(f"aggregate.json: {e}")
        try:
            p = out / "sku_week.json"
            if p.exists():
                sku = json.loads(p.read_text(encoding="utf-8"))
            else:
                err_msgs.append(f"missing: {p}")
        except Exception as e:
            err_msgs.append(f"sku_week.json: {e}")
        try:
            p = out / "mrp.json"
            if p.exists():
                mrp = json.loads(p.read_text(encoding="utf-8"))
            else:
                err_msgs.append(f"missing: {p}")
        except Exception as e:
            err_msgs.append(f"mrp.json: {e}")
        try:
            p = out / "plan_final.json"
            if p.exists():
                plan = json.loads(p.read_text(encoding="utf-8"))
            else:
                err_msgs.append(f"missing: {p}")
        except Exception as e:
            err_msgs.append(f"plan_final.json: {e}")
        # reconciliation_log.json の読み込み（存在すれば）
        try:
            p = out / "reconciliation_log.json"
            if p.exists():
                recon = json.loads(p.read_text(encoding="utf-8"))
                # 相対パス（ダウンロード用のリンク表示）
                rel_dir = str(out.relative_to(_BASE_DIR))
                rp = _BASE_DIR / rel_dir / "reconciliation_log.json"
                recon_path = (
                    str((rp).relative_to(_BASE_DIR))
                    if rp.exists()
                    else str(Path(rel_dir) / "reconciliation_log.json")
                )
            else:
                # 必須ではないので missing はエラーにしない
                pass
        except Exception as e:
            err_msgs.append(f"reconciliation_log.json: {e}")
        # 調整後の成果物（存在すれば）
        try:
            p = out / "plan_final_adjusted.json"
            if p.exists():
                plan_adj = json.loads(p.read_text(encoding="utf-8"))
            p = out / "sku_week_adjusted.json"
            anchor_adj = None
            if p.exists():
                anchor_adj = json.loads(p.read_text(encoding="utf-8"))
            p = out / "reconciliation_log_adjusted.json"
            if p.exists():
                recon_adj = json.loads(p.read_text(encoding="utf-8"))
                rel_dir = str(out.relative_to(_BASE_DIR))
                rp3 = _BASE_DIR / rel_dir / "reconciliation_log_adjusted.json"
                recon_adj_path = (
                    str((rp3).relative_to(_BASE_DIR))
                    if rp3.exists()
                    else str(Path(rel_dir) / "reconciliation_log_adjusted.json")
                )
        except Exception as e:
            err_msgs.append(f"adjusted artifacts: {e}")
        # report.csv は存在しなくてもリンクを示せるように相対パスを構築
        try:
            rel_dir = str(out.relative_to(_BASE_DIR))
            rp = _BASE_DIR / rel_dir / "report.csv"
            report = (
                str((rp).relative_to(_BASE_DIR))
                if rp.exists()
                else str(Path(rel_dir) / "report.csv")
            )
            rp2 = _BASE_DIR / rel_dir / "report_adjusted.csv"
            report_adj = (
                str((rp2).relative_to(_BASE_DIR))
                if rp2.exists()
                else (str(Path(rel_dir) / "report_adjusted.csv") if (out / "report_adjusted.csv").exists() else None)
            )
        except Exception as e:
            # out が _BASE_DIR 配下でない場合など
            rp = out / "report.csv"
            report = str(rp)
            err_msgs.append(f"report.csv: {e}")
        # before/after 差分比較（上位20件）
        recon_compare = None
        recon_summary = None
        try:
            if recon and recon_adj and isinstance(recon.get("deltas"), list) and isinstance(recon_adj.get("deltas"), list):
                before_list = recon.get("deltas")
                after_map = { (str(r.get("family")), str(r.get("period"))) : r for r in recon_adj.get("deltas") }
                def _absmax(row: dict) -> float:
                    try:
                        return max(abs(float(row.get("delta_demand", 0) or 0)), abs(float(row.get("delta_supply", 0) or 0)), abs(float(row.get("delta_backlog", 0) or 0)))
                    except Exception:
                        return 0.0
                top = sorted(before_list, key=_absmax, reverse=True)[:20]
                comp = []
                for r in top:
                    key = (str(r.get("family")), str(r.get("period")))
                    a = after_map.get(key) or {}
                    comp.append({
                        "family": key[0],
                        "period": key[1],
                        "before": {
                            "demand": r.get("delta_demand"),
                            "supply": r.get("delta_supply"),
                            "backlog": r.get("delta_backlog"),
                            "rel_demand": r.get("rel_demand"),
                            "rel_supply": r.get("rel_supply"),
                            "rel_backlog": r.get("rel_backlog"),
                            "ok": r.get("ok"),
                            "ok_demand": r.get("ok_demand"),
                            "ok_supply": r.get("ok_supply"),
                            "ok_backlog": r.get("ok_backlog"),
                        },
                        "after": {
                            "demand": a.get("delta_demand"),
                            "supply": a.get("delta_supply"),
                            "backlog": a.get("delta_backlog"),
                            "rel_demand": a.get("rel_demand"),
                            "rel_supply": a.get("rel_supply"),
                            "rel_backlog": a.get("rel_backlog"),
                            "ok": a.get("ok"),
                            "ok_demand": a.get("ok_demand"),
                            "ok_supply": a.get("ok_supply"),
                            "ok_backlog": a.get("ok_backlog"),
                        },
                    })
                recon_compare = comp
                # 要約: 総|Δ|の before/after と改善率
                def total_abs(rows):
                    s = 0.0
                    for r in rows:
                        try:
                            s += abs(float(r.get("delta_demand", 0) or 0))
                            s += abs(float(r.get("delta_supply", 0) or 0))
                            s += abs(float(r.get("delta_backlog", 0) or 0))
                        except Exception:
                            pass
                    return s
                before_total = total_abs(before_list)
                after_total = total_abs(list(after_map.values()))
                impr = (1.0 - after_total / before_total) * 100.0 if before_total > 0 else 0.0
                recon_summary = {
                    "before_total": round(before_total, 6),
                    "after_total": round(after_total, 6),
                    "improvement_pct": round(impr, 2),
                }
        except Exception:
            recon_compare = None
            recon_summary = None
    return templates.TemplateResponse(
        "planning.html",
        {
            "request": request,
            "subtitle": "集約/詳細計画",
            "out_dir": str(out) if out else "",
            "aggregate": agg,
            "plan": plan,
            "plan_adj": plan_adj,
            "sku": sku,
            "mrp": mrp,
            "recon": recon,
            "recon_path": recon_path,
            "recon_adj": recon_adj,
            "recon_adj_path": recon_adj_path,
            "anchor_adj": anchor_adj if 'anchor_adj' in locals() else None,
            "recon_compare": recon_compare,
            "recon_summary": recon_summary,
            "report_path": report,
            "report_adj_path": report_adj,
            "error": "\n".join(err_msgs) if err_msgs else None,
        },
    )


@app.post("/planning/run")
def planning_run(
    request: Request,
    input_dir: str = Form("samples/planning"),
    out_dir: str | None = Form(None),
    weeks: int = Form(4),
    round_mode: str = Form("int"),
    lt_unit: str = Form("day"),
    version_id: str = Form("") ,
    cutover_date: str | None = Form(None),
    recon_window_days: int | None = Form(None),
    anchor_policy: str | None = Form(None),
    calendar_mode: str | None = Form(None),
    carryover: str | None = Form(None),
    carryover_split: float | None = Form(None),
    max_adjust_ratio: float | None = Form(None),
    tol_abs: float | None = Form(None),
    tol_rel: float | None = Form(None),
    apply_adjusted: int | None = Form(None),
    demand_family: UploadFile | None = File(None),
    capacity: UploadFile | None = File(None),
    mix_share: UploadFile | None = File(None),
    item: UploadFile | None = File(None),
    inventory: UploadFile | None = File(None),
    open_po: UploadFile | None = File(None),
    bom: UploadFile | None = File(None),
):
    ts = int(time.time())
    out_base = Path(out_dir) if out_dir else (_BASE_DIR / "out" / f"ui_planning_{ts}")
    out_base.mkdir(parents=True, exist_ok=True)
    # optional: uploaded CSVs → override input_dir into temp folder
    upload_files = {
        "demand_family.csv": demand_family,
        "capacity.csv": capacity,
        "mix_share.csv": mix_share,
        "item.csv": item,
        "inventory.csv": inventory,
        "open_po.csv": open_po,
        "bom.csv": bom,
    }
    # 実際にファイルが与えられたか（filenameが非空、かつ内容が非空）で判定
    tmp_in = out_base / "input"
    wrote_any = False
    for name, uf in upload_files.items():
        try:
            if uf is None:
                continue
            fname = getattr(uf, "filename", None) or ""
            if not fname.strip():
                continue
            content = uf.file.read() or b""
            if len(content) == 0:
                continue
            tmp_in.mkdir(parents=True, exist_ok=True)
            (tmp_in / name).write_bytes(content)
            wrote_any = True
        except Exception:
            # 個別の失敗は無視（他の入力にフォールバック）
            continue
    if wrote_any:
        input_dir = str(tmp_in)

    # 1) aggregate
    _run_py(
        [
            "scripts/plan_aggregate.py",
            "-i",
            input_dir,
            "-o",
            str(out_base / "aggregate.json"),
        ]
    )
    # 2) allocate
    _run_py(
        [
            "scripts/allocate.py",
            "-i",
            str(out_base / "aggregate.json"),
            "-I",
            input_dir,
            "-o",
            str(out_base / "sku_week.json"),
            "--weeks",
            str(weeks),
            "--round",
            round_mode,
        ]
    )
    # 3) mrp
    _run_py(
        [
            "scripts/mrp.py",
            "-i",
            str(out_base / "sku_week.json"),
            "-I",
            input_dir,
            "-o",
            str(out_base / "mrp.json"),
            "--lt-unit",
            lt_unit,
            "--weeks",
            str(weeks),
        ]
    )
    # 4) reconcile
    _run_py(
        [
            "scripts/reconcile.py",
            "-i",
            str(out_base / "sku_week.json"),
            str(out_base / "mrp.json"),
            "-I",
            input_dir,
            "-o",
            str(out_base / "plan_final.json"),
            "--weeks",
            str(weeks),
        ]
    )
    # 4.5) reconcile-levels (AGG↔DET 差分ログ)
    _run_py(
        [
            "scripts/reconcile_levels.py",
            "-i",
            str(out_base / "aggregate.json"),
            str(out_base / "sku_week.json"),
            "-o",
            str(out_base / "reconciliation_log.json"),
            "--version",
            (version_id or "ui"),
            *(["--cutover-date", cutover_date] if cutover_date else []),
            *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
            *(["--anchor-policy", anchor_policy] if anchor_policy else []),
            *(["--tol-abs", str(tol_abs)] if tol_abs is not None else ["--tol-abs", "1e-6"]),
            *(["--tol-rel", str(tol_rel)] if tol_rel is not None else ["--tol-rel", "1e-6"]),
        ]
    )
    # export before CSV
    _run_py(
        [
            "scripts/export_reconcile_csv.py",
            "-i",
            str(out_base / "reconciliation_log.json"),
            "-o",
            str(out_base / "reconciliation_before.csv"),
            "--label",
            "before",
        ]
    )
    _run_py(
        [
            "scripts/export_reconcile_csv.py",
            "-i",
            str(out_base / "reconciliation_log.json"),
            "-o",
            str(out_base / "reconciliation_violations_before.csv"),
            "--label",
            "before",
            "--only-violations",
        ]
    )
    # optional: anchor=DET_near 調整（検証用、MRP再計算は行わない）
    if anchor_policy and cutover_date:
        _run_py(
            [
                "scripts/anchor_adjust.py",
                "-i",
                str(out_base / "aggregate.json"),
                str(out_base / "sku_week.json"),
                "-o",
                str(out_base / "sku_week_adjusted.json"),
                "--cutover-date",
                str(cutover_date),
                "--anchor-policy",
                str(anchor_policy),
                *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
                "--weeks",
                str(weeks),
                *(["--calendar-mode", str(calendar_mode)] if calendar_mode else []),
                *(["--carryover", str(carryover)] if carryover else []),
                *(["--carryover-split", str(carryover_split)] if (carryover_split is not None) else []),
                *(["--max-adjust-ratio", str(max_adjust_ratio)] if (max_adjust_ratio is not None) else []),
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
                str(out_base / "aggregate.json"),
                str(out_base / "sku_week_adjusted.json"),
                "-o",
                str(out_base / "reconciliation_log_adjusted.json"),
                "--version",
                (version_id or "ui-adjusted"),
                "--cutover-date",
                str(cutover_date),
                *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
                *(["--anchor-policy", anchor_policy] if anchor_policy else []),
                *(["--tol-abs", str(tol_abs)] if tol_abs is not None else ["--tol-abs", "1e-6"]),
                *(["--tol-rel", str(tol_rel)] if tol_rel is not None else ["--tol-rel", "1e-6"]),
            ]
        )
        # export compare CSV and carryover CSV
        _run_py(
            [
                "scripts/export_reconcile_csv.py",
                "-i",
                str(out_base / "reconciliation_log.json"),
                "--label",
                "before",
                "-j",
                str(out_base / "reconciliation_log_adjusted.json"),
                "--label2",
                "after",
                "-o",
                str(out_base / "reconciliation_compare.csv"),
            ]
        )
        _run_py(
            [
                "scripts/export_reconcile_csv.py",
                "-i",
                str(out_base / "reconciliation_log.json"),
                "--label",
                "before",
                "-j",
                str(out_base / "reconciliation_log_adjusted.json"),
                "--label2",
                "after",
                "-o",
                str(out_base / "reconciliation_violations_compare.csv"),
                "--only-violations",
            ]
        )
        _run_py(
            [
                "scripts/export_carryover_csv.py",
                "-i",
                str(out_base / "sku_week_adjusted.json"),
                "-o",
                str(out_base / "carryover.csv"),
            ]
        )
        if apply_adjusted:
            _run_py(
                [
                    "scripts/mrp.py",
                    "-i",
                    str(out_base / "sku_week_adjusted.json"),
                    "-I",
                    input_dir,
                    "-o",
                    str(out_base / "mrp_adjusted.json"),
                    "--lt-unit",
                    lt_unit,
                    "--weeks",
                    str(weeks),
                ]
            )
            _run_py(
                [
                    "scripts/reconcile.py",
                    "-i",
                    str(out_base / "sku_week_adjusted.json"),
                    str(out_base / "mrp_adjusted.json"),
                    "-I",
                    input_dir,
                    "-o",
                    str(out_base / "plan_final_adjusted.json"),
                    "--weeks",
                    str(weeks),
                    *(["--cutover-date", cutover_date] if cutover_date else []),
                    *(["--recon-window-days", str(recon_window_days)] if recon_window_days is not None else []),
                    *(["--anchor-policy", anchor_policy] if anchor_policy else []),
                ]
            )
            _run_py(
                [
                    "scripts/report.py",
                    "-i",
                    str(out_base / "plan_final_adjusted.json"),
                    "-I",
                    input_dir,
                    "-o",
                    str(out_base / "report_adjusted.csv"),
                ]
            )
    # 5) report
    _run_py(
        [
            "scripts/report.py",
            "-i",
            str(out_base / "plan_final.json"),
            "-I",
            input_dir,
            "-o",
            str(out_base / "report.csv"),
        ]
    )
    rel = str(out_base.relative_to(_BASE_DIR))
    return RedirectResponse(url=f"/ui/planning?dir={rel}", status_code=303)


@app.post("/planning/run_job")
def planning_run_job(
    input_dir: str = Form("samples/planning"),
    out_dir: str | None = Form(None),
    weeks: int = Form(4),
    round_mode: str = Form("int"),
    lt_unit: str = Form("day"),
    version_id: str = Form(""),
    cutover_date: str | None = Form(None),
    recon_window_days: int | None = Form(None),
    anchor_policy: str | None = Form(None),
    calendar_mode: str | None = Form(None),
    carryover: str | None = Form(None),
    carryover_split: float | None = Form(None),
    max_adjust_ratio: float | None = Form(None),
    tol_abs: float | None = Form(None),
    tol_rel: float | None = Form(None),
    apply_adjusted: int | None = Form(None),
):
    params = {
        "input_dir": input_dir,
        "out_dir": out_dir,
        "weeks": weeks,
        "round_mode": round_mode,
        "lt_unit": lt_unit,
        "version_id": version_id,
        "cutover_date": cutover_date,
        "recon_window_days": recon_window_days,
        "anchor_policy": anchor_policy,
        "calendar_mode": calendar_mode,
        "max_adjust_ratio": max_adjust_ratio,
        "carryover": carryover,
        "carryover_split": carryover_split,
        "apply_adjusted": bool(apply_adjusted),
        "tol_abs": tol_abs,
        "tol_rel": tol_rel,
    }
    job_id = JOB_MANAGER.submit_planning(params)
    return RedirectResponse(url="/ui/jobs", status_code=303)
