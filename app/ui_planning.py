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
    err = None
    if dir:
        out = Path(dir)
        try:
            if not out.is_absolute():
                out = _BASE_DIR / out
            agg = json.loads((out / "aggregate.json").read_text(encoding="utf-8"))
            plan_json = json.loads((out / "plan_final.json").read_text(encoding="utf-8"))
            report_path = out / "report.csv"
            sku = json.loads((out / "sku_week.json").read_text(encoding="utf-8"))
            mrp = json.loads((out / "mrp.json").read_text(encoding="utf-8"))
            plan = plan_json
            report = str(report_path.relative_to(_BASE_DIR)) if report_path.exists() else None
        except Exception as e:
            err = str(e)
    return templates.TemplateResponse(
        "planning.html",
        {
            "request": request,
            "subtitle": "Planning Pipeline",
            "out_dir": str(out) if out else "",
            "aggregate": agg,
            "plan": plan,
            "sku": sku,
            "mrp": mrp,
            "report_path": report,
            "error": err,
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
    _run_py(["scripts/plan_aggregate.py", "-i", input_dir, "-o", str(out_base / "aggregate.json")])
    # 2) allocate
    _run_py([
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
    ])
    # 3) mrp
    _run_py([
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
    ])
    # 4) reconcile
    _run_py([
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
    ])
    # 5) report
    _run_py([
        "scripts/report.py",
        "-i",
        str(out_base / "plan_final.json"),
        "-I",
        input_dir,
        "-o",
        str(out_base / "report.csv"),
    ])
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
