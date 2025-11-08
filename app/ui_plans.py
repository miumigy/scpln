from fastapi import APIRouter, Query, Request, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
import sys
import os
import json
import logging
import tempfile
import shutil
import datetime

from core.config.storage import (
    get_planning_input_set,
    list_planning_input_sets,
    PlanningInputSetNotFoundError,
    list_canonical_configs, # 追加
)
from core.config.importer import import_planning_inputs # 追加
from app.api import templates

router = APIRouter()

_BASE_DIR = Path(__file__).resolve().parents[1]

@router.get("/ui/plans/input_sets/upload", response_class=HTMLResponse)
def ui_get_input_set_upload_form(request: Request):
    canonical_options = list_canonical_configs()
    return templates.TemplateResponse(
        request,
        "input_set_upload.html",
        {
            "subtitle": "Upload Input Set",
            "canonical_options": canonical_options,
        },
    )

@router.post("/ui/plans/input_sets/upload", response_class=HTMLResponse)
async def ui_post_input_set_upload(
    request: Request,
    config_version_id: int = Form(...),
    label: str = Form(...),
    files: list[UploadFile] = File(...),
):
    if not label or not label.strip():
        raise HTTPException(status_code=400, detail="Input Set Label is required.")
    if not config_version_id:
        raise HTTPException(status_code=400, detail="Canonical Config Version is required.")

    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="input-set-upload-"))
        uploaded_file_paths = []
        for file in files:
            file_path = temp_dir / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_file_paths.append(file_path)
        
        logging.info(f"Uploaded files for input set '{label}' (config_version_id: {config_version_id}) to: {temp_dir}")
        for p in uploaded_file_paths:
            logging.info(f" - {p}")

        # ここで検証ロジックを呼び出す
        # 現時点では成功としてリダイレクト
        try:
            result = import_planning_inputs(
                directory=temp_dir,
                config_version_id=config_version_id,
                label=label,
                apply_mode="replace",  # UIからのアップロードは常にreplaceモードとする
                validate_only=False,
            )
            if result["status"] == "error":
                raise HTTPException(status_code=400, detail=result["message"])

            return RedirectResponse(url=f"/ui/plans/input_sets/{label}", status_code=303)
        except HTTPException:
            raise # re-raise HTTPException
        except Exception as e:
            logging.exception("Failed to import planning inputs.")
            raise HTTPException(status_code=500, detail=f"Failed to import planning inputs: {e}")
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir)

@router.get("/ui/plans/input_sets", response_class=HTMLResponse)
def ui_list_input_sets(request: Request):
    input_sets = list_planning_input_sets(status="ready")
    return templates.TemplateResponse(
        request,
        "input_sets.html",
        {
            "subtitle": "Planning Input Sets",
            "input_sets": input_sets,
        },
    )

@router.get("/ui/plans/input_sets/{label}", response_class=HTMLResponse)
def ui_get_input_set_detail(label: str, request: Request):
    try:
        input_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    return templates.TemplateResponse(
        request,
        "input_set_detail.html",
        {
            "subtitle": f"Input Set: {label}",
            "input_set": input_set,
        },
    )

@router.get("/ui/plans/input_sets/{label}/diff", response_class=HTMLResponse)
def ui_plan_input_set_diff(
    label: str,
    request: Request,
    against: str | None = Query(None, description="Label of the input set to compare against. Defaults to latest ready set."),
):
    import tempfile
    import shutil
    import subprocess
    from fastapi import BackgroundTasks

    background_tasks = BackgroundTasks()

    try:
        current_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    other_label = against
    other_set = None
    if not other_label:
        # Find latest ready set with the same config_version_id
        summaries = list_planning_input_sets(
            config_version_id=current_set.config_version_id,
            status="ready",
            limit=10
        )
        # Find the most recent one that is not the current one
        for s in sorted(summaries, key=lambda x: x.updated_at or 0, reverse=True):
            if s.label != label:
                other_label = s.label
                break

    if other_label:
        try:
            other_set = get_planning_input_set(label=other_label, include_aggregates=True)
        except PlanningInputSetNotFoundError:
            pass # Fallback to no diff

    diff_report = None
    if other_set and other_label:
        temp_dir = tempfile.mkdtemp(prefix="plan-diff-")
        background_tasks.add_task(shutil.rmtree, temp_dir)
        script_path = str(_BASE_DIR / "scripts" / "export_planning_inputs.py")
        args = [
            sys.executable,
            script_path,
            "--label",
            label,
            "--diff-against",
            other_label,
            "--output-dir",
            str(temp_dir),
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONPATH", str(_BASE_DIR))
        try:
            subprocess.run(args, cwd=str(_BASE_DIR), env=env, check=True, capture_output=True, text=True)
            diff_path = Path(temp_dir) / "diff_report.json"
            if diff_path.exists():
                diff_report = json.loads(diff_path.read_text(encoding="utf-8"))
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Failed to generate or read diff report: {e}")
            # Allow rendering the page without a diff
            pass

    return templates.TemplateResponse(
        request,
        "input_set_diff.html",
        {
            "subtitle": f"Input Set Diff: {label}",
            "current_set": current_set,
            "other_set": other_set,
            "diff_report": diff_report,
        },
    )