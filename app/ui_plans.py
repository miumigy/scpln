from fastapi import APIRouter, Query, Request, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import sys
import os
import json
import logging
import tempfile
import shutil
import time
import subprocess
import re

from core.config.storage import (
    get_planning_input_set,
    list_planning_input_sets,
    update_planning_input_set,
    list_planning_input_set_events,
    log_planning_input_set_event,
    PlanningInputSetNotFoundError,
    list_canonical_version_summaries,
)
from core.config.importer import import_planning_inputs
from app.metrics import (
    INPUT_SET_DIFF_JOBS_TOTAL,
    INPUT_SET_DIFF_CACHE_HITS_TOTAL,
    INPUT_SET_DIFF_CACHE_STALE_TOTAL,
)

router = APIRouter()

_BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
_DIFF_CACHE_DIR = _BASE_DIR / "tmp" / "input_set_diffs"
_DIFF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_DIFF_CACHE_TTL_SECONDS = 600
_DIFF_LOCK_TTL_SECONDS = 600
_SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")


def _safe_slug(value: str | None) -> str:
    if not value:
        return "unknown"
    slug = _SLUG_PATTERN.sub("-", value).strip("-").lower()
    return slug or "unknown"


def _list_canonical_options() -> list[dict[str, object]]:
    summaries = list_canonical_version_summaries(limit=100)
    options: list[dict[str, object]] = []
    for summary in summaries:
        meta = summary.meta
        version_id = meta.version_id
        if version_id is None:
            continue
        display_name = meta.name or f"Version {version_id}"
        num_calendars = summary.counts.get("calendars", 0)
        options.append(
            {
                "id": version_id,
                "label": f"{display_name} (v{version_id})",
                "num_calendars": num_calendars,
            }
        )
    return options


def _diff_cache_paths(label: str, other_label: str) -> tuple[Path, Path]:
    key = f"{_safe_slug(label)}__{_safe_slug(other_label)}"
    cache_path = _DIFF_CACHE_DIR / f"{key}.json"
    lock_path = _DIFF_CACHE_DIR / f"{key}.lock"
    return cache_path, lock_path


def _load_cached_diff(cache_path: Path) -> tuple[dict | None, int | None]:
    if not cache_path.exists():
        return None, None
    age = time.time() - cache_path.stat().st_mtime
    if age > _DIFF_CACHE_TTL_SECONDS:
        try:
            INPUT_SET_DIFF_CACHE_STALE_TOTAL.inc()
        except Exception:
            pass
        return None, None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        generated_at = int(cache_path.stat().st_mtime * 1000)
        try:
            INPUT_SET_DIFF_CACHE_HITS_TOTAL.inc()
        except Exception:
            pass
        return data, generated_at
    except Exception:
        logging.exception("input_set_diff_cache_load_failed", extra={"cache": str(cache_path)})
        try:
            INPUT_SET_DIFF_CACHE_STALE_TOTAL.inc()
        except Exception:
            pass
        return None, None


def _is_lock_active(lock_path: Path) -> bool:
    if not lock_path.exists():
        return False
    age = time.time() - lock_path.stat().st_mtime
    if age > _DIFF_LOCK_TTL_SECONDS:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            logging.warning("input_set_diff_lock_cleanup_failed", exc_info=True)
        return False
    return True


def _schedule_diff_generation(
    background_tasks: BackgroundTasks,
    label: str,
    other_label: str,
    cache_path: Path,
    lock_path: Path,
) -> None:
    try:
        lock_path.touch()
    except Exception:
        logging.warning("input_set_diff_lock_touch_failed", exc_info=True)
    background_tasks.add_task(_generate_diff_report, label, other_label, cache_path, lock_path)


def _generate_diff_report(label: str, other_label: str, cache_path: Path, lock_path: Path) -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="input-set-diff-"))
    try:
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
        result = subprocess.run(
            args,
            cwd=str(_BASE_DIR),
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logging.error(
                "input_set_diff_job_failed",
                extra={"label": label, "against": other_label, "stderr": result.stderr},
            )
            try:
                INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
            except Exception:
                pass
            return
        diff_path = temp_dir / "diff_report.json"
        if diff_path.exists():
            cache_path.write_text(diff_path.read_text(encoding="utf-8"), encoding="utf-8")
            try:
                INPUT_SET_DIFF_JOBS_TOTAL.labels(result="success").inc()
            except Exception:
                pass
        else:
            logging.error(
                "input_set_diff_job_missing_output",
                extra={"label": label, "against": other_label},
            )
            try:
                INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
            except Exception:
                pass
    except Exception:
        logging.exception(
            "input_set_diff_job_exception",
            extra={"label": label, "against": other_label},
        )
        try:
            INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
        except Exception:
            pass
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            logging.warning("input_set_diff_temp_cleanup_failed", exc_info=True)
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            logging.warning("input_set_diff_lock_remove_failed", exc_info=True)

@router.get("/ui/plans/input_sets/upload", response_class=HTMLResponse)
def ui_get_input_set_upload_form(request: Request):
    canonical_options = _list_canonical_options()
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

    if not files or all((not f.filename) for f in files):
        raise HTTPException(status_code=400, detail="At least one CSV file is required.")

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
                status="draft",
                source="ui",
                created_by="ui_upload_form",
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
    status_query = (request.query_params.get("status") or "ready").lower()
    status_filter = None if status_query == "all" else status_query
    input_sets = list_planning_input_sets(status=status_filter)
    status_options = [
        ("all", "All"),
        ("draft", "Draft"),
        ("ready", "Ready"),
        ("archived", "Archived"),
    ]
    return templates.TemplateResponse(
        request,
        "input_sets.html",
        {
            "subtitle": "Planning Input Sets",
            "input_sets": input_sets,
            "status_options": status_options,
            "selected_status": status_query,
        },
    )

@router.get("/ui/plans/input_sets/{label}", response_class=HTMLResponse)
def ui_get_input_set_detail(label: str, request: Request):
    try:
        input_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")
    events = list_planning_input_set_events(input_set.id, limit=100) if input_set.id else []

    return templates.TemplateResponse(
        request,
        "input_set_detail.html",
        {
            "subtitle": f"Input Set: {label}",
            "input_set": input_set,
            "input_set_events": events,
        },
    )


@router.post("/ui/plans/input_sets/{label}/review", response_class=HTMLResponse)
async def ui_review_input_set(
    label: str,
    request: Request,
    action: str = Form(...),
    reviewer: str = Form(""),
    review_comment: str = Form(""),
):
    try:
        input_set = get_planning_input_set(label=label, include_aggregates=False)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    if input_set.status == "archived":
        raise HTTPException(status_code=400, detail="Archived input sets cannot be reviewed.")

    reviewer_value = reviewer.strip() or "ui_reviewer"
    comment_value = review_comment.strip() or None

    try:
        if action == "approve":
            update_planning_input_set(
                input_set.id,
                status="ready",
                approved_by=reviewer_value,
                approved_at=int(time.time() * 1000),
                review_comment=comment_value,
            )
            log_planning_input_set_event(
                input_set.id,
                action="approve",
                actor=reviewer_value,
                comment=comment_value,
                metadata={"source": "ui_review"},
            )
        elif action == "revert":
            update_planning_input_set(
                input_set.id,
                status="draft",
                approved_by=None,
                approved_at=None,
                review_comment=comment_value,
            )
            log_planning_input_set_event(
                input_set.id,
                action="revert",
                actor=reviewer_value,
                comment=comment_value,
                metadata={"source": "ui_review"},
            )
        else:
            raise HTTPException(status_code=400, detail="Unsupported review action.")
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    return RedirectResponse(url=f"/ui/plans/input_sets/{label}", status_code=303)


@router.get("/ui/plans/input_sets/{label}/diff", response_class=HTMLResponse)
def ui_plan_input_set_diff(
    label: str,
    request: Request,
    against: str | None = Query(None, description="Label of the input set to compare against. Defaults to latest ready set."),
):
    background_tasks = BackgroundTasks()

    try:
        current_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    other_label = against
    other_set = None
    if not other_label:
        summaries = list_planning_input_sets(
            config_version_id=current_set.config_version_id,
            status="ready",
            limit=10,
        )
        for s in sorted(summaries, key=lambda x: x.updated_at or 0, reverse=True):
            if s.label != label:
                other_label = s.label
                break

    if other_label:
        try:
            other_set = get_planning_input_set(label=other_label, include_aggregates=True)
        except PlanningInputSetNotFoundError:
            other_set = None

    diff_report = None
    diff_generated_at = None
    diff_generating = False
    if other_set and other_label:
        cache_path, lock_path = _diff_cache_paths(label, other_label)
        diff_report, diff_generated_at = _load_cached_diff(cache_path)
        if diff_report is None:
            diff_generating = _is_lock_active(lock_path)
            if not diff_generating:
                _schedule_diff_generation(
                    background_tasks,
                    label,
                    other_label,
                    cache_path,
                    lock_path,
                )
                diff_generating = True

    return templates.TemplateResponse(
        request,
        "input_set_diff.html",
        {
            "subtitle": f"Input Set Diff: {label}",
            "current_set": current_set,
            "other_set": other_set,
            "diff_report": diff_report,
            "diff_generating": diff_generating,
            "diff_generated_at": diff_generated_at,
        },
        background=background_tasks,
    )
