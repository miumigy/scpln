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
    agg = sku = mrp = plan = report = None
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
        # report.csv は存在しなくてもリンクを示せるように相対パスを構築
        try:
            rel_dir = str(out.relative_to(_BASE_DIR))
            rp = _BASE_DIR / rel_dir / "report.csv"
            report = str((rp).relative_to(_BASE_DIR)) if rp.exists() else str(
                Path(rel_dir) / "report.csv"
            )
        except Exception as e:
            # out が _BASE_DIR 配下でない場合など
            rp = out / "report.csv"
            report = str(rp)
            err_msgs.append(f"report.csv: {e}")
    return templates.TemplateResponse(
        "planning.html",
        {
            "request": request,
            "subtitle": "集約/詳細計画",
            "out_dir": str(out) if out else "",
            "aggregate": agg,
            "plan": plan,
            "sku": sku,
            "mrp": mrp,
            "report_path": report,
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
    has_upload = any(f is not None for f in upload_files.values())
    if has_upload:
        tmp_in = out_base / "input"
        tmp_in.mkdir(parents=True, exist_ok=True)
        for name, uf in upload_files.items():
            if uf is None:
                continue
            content = uf.file.read()
            (tmp_in / name).write_bytes(content)
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
):
    params = {
        "input_dir": input_dir,
        "out_dir": out_dir,
        "weeks": weeks,
        "round_mode": round_mode,
        "lt_unit": lt_unit,
    }
    job_id = JOB_MANAGER.submit_planning(params)
    return RedirectResponse(url="/ui/jobs", status_code=303)
