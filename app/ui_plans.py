import logging
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import db
from app.config_api import _list_canonical_options
from app.run_registry_db import table_exists
from core.plan_repository import (
    get_planning_input_set,
    list_planning_input_set_events,
    list_planning_input_sets,
    list_planning_runs,
    PlanningInputSetNotFoundError,
    update_planning_input_set,
    log_planning_input_set_event,
)
from core.plan_repository_builders import import_planning_inputs
from core.plan_repository_views import (
    get_planning_run_detail,
    list_canonical_version_summaries,
    list_plan_versions,
)
from scripts.plan_pipeline_io import (
    _diff_cache_paths,
    _is_lock_active,
    _load_cached_diff,
    _prepare_delta_rows,
    _schedule_diff_generation,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

_BASE_DIR = Path(__file__).resolve().parent.parent
_DIFF_TABLE_LIMIT = 100


class PlanningRunForm(BaseModel):
    plan_version_id: int = Field(..., description="計画バージョンID")
    label: str = Field(..., description="実行ラベル")


def _fetch_plan_rows(limit: int = 50, offset: int = 0):
    plans = list_plan_versions(limit=limit, offset=offset)
    total_count = db.count_table_rows("plan_versions")
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_next": (offset + limit) < total_count,
        "has_previous": offset > 0,
        "next_offset": offset + limit,
        "previous_offset": max(0, offset - limit),
    }
    return plans, pagination


def _render_plans_page(request: Request, plans, pagination, has_data: bool):
    return templates.TemplateResponse(
        request,
        "plans.html",
        {
            "subtitle": "Planning Hub",
            "plans": plans,
            "pagination": pagination,
            "has_data": has_data,
        },
    )


@router.get("/ui/plans", response_class=HTMLResponse)
def ui_plans(request: Request, limit: int = 50, offset: int = 0):
    has_data = False
    rows, pagination = [], {}
    if table_exists(db._conn(), "plan_versions"):
        rows, pagination = _fetch_plan_rows(limit=limit, offset=offset)
        if rows:
            has_data = True

    # paginationがNoneになる可能性を考慮し、空の辞書をデフォルトとする
    pagination = pagination if pagination is not None else {}

    return _render_plans_page(
        request, plans=rows, pagination=pagination, has_data=has_data
    )


def _list_sample_input_sets() -> list[dict[str, str]]:
    """Scan samples/planning_input_sets for available sample sets."""
    sample_dir = _BASE_DIR / "samples" / "planning_input_sets"
    if not sample_dir.is_dir():
        return []

    samples = []
    for d in sample_dir.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            samples.append(
                {
                    "name": d.name,
                    "description": meta.get("description", d.name),
                }
            )
        except Exception:
            logging.warning(
                f"Failed to parse meta.json for sample: {d.name}", exc_info=True
            )
    return sorted(samples, key=lambda x: x["name"])


@router.post("/ui/plans/input_sets/sample", response_class=HTMLResponse)
async def ui_post_load_sample_input_set(request: Request, sample_name: str = Form(...)):
    """Load a predefined sample input set into the database."""
    error_url = "/ui/plans/input_sets?error="
    sample_dir = _BASE_DIR / "samples" / "planning_input_sets" / sample_name
    if not sample_dir.is_dir():
        raise HTTPException(
            status_code=404, detail=f"Sample '{sample_name}' not found."
        )

    meta_path = sample_dir / "meta.json"
    if not meta_path.is_file():
        raise HTTPException(
            status_code=404, detail=f"meta.json for sample '{sample_name}' not found."
        )

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        label = meta.get("label")
        canonical_sample_name = meta.get("canonical_sample_name")
        if not label or not canonical_sample_name:
            return RedirectResponse(
                url=error_url + "Invalid_meta_json", status_code=303
            )

        # Find the corresponding canonical config version ID
        config_version_id = None
        summaries = list_canonical_version_summaries(limit=1000)
        for summary in summaries:
            if summary.meta.path and summary.meta.path.endswith(canonical_sample_name):
                config_version_id = summary.meta.version_id
                break

        if not config_version_id:
            return RedirectResponse(
                url=error_url
                + f"Canonical_config_for_{canonical_sample_name}_not_found",
                status_code=303,
            )

        # Import the sample data
        result = import_planning_inputs(
            directory=sample_dir,
            config_version_id=config_version_id,
            label=label,
            apply_mode="replace",
            validate_only=False,
            status="draft",
            source="sample",
            created_by="ui_load_sample",
        )
        if result.get("status") == "error":
            return RedirectResponse(
                url=error_url + result.get("message", "Import_failed"), status_code=303
            )

        return RedirectResponse(url=f"/ui/plans/input_sets/{label}", status_code=303)

    except Exception as e:
        logging.exception("Failed to load sample input set.")
        return RedirectResponse(url=error_url + f"Internal_error_{e}", status_code=303)


@router.get("/ui/plans/input_sets", response_class=HTMLResponse)
def ui_list_input_sets(request: Request):
    status_query = (request.query_params.get("status") or "ready").lower()
    status_filter = None if status_query == "all" else status_query
    input_sets = list_planning_input_sets(status=status_filter)
    sample_input_sets = _list_sample_input_sets()
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
            "sample_input_sets": sample_input_sets,
            "status_options": status_options,
            "selected_status": status_query,
        },
    )


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
        raise HTTPException(
            status_code=400, detail="Canonical Config Version is required."
        )

    if not files or all((not f.filename) for f in files):
        raise HTTPException(
            status_code=400, detail="At least one CSV file is required."
        )

    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="input-set-upload-"))
        uploaded_file_paths = []
        for file in files:
            file_path = temp_dir / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_file_paths.append(file_path)

        logging.info(
            f"Uploaded files for input set '{label}' (config_version_id: {config_version_id}) to: {temp_dir}"
        )
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

            return RedirectResponse(
                url=f"/ui/plans/input_sets/{label}", status_code=303
            )
        except HTTPException:
            raise  # re-raise HTTPException
        except Exception as e:
            logging.exception("Failed to import planning inputs.")
            raise HTTPException(
                status_code=500, detail=f"Failed to import planning inputs: {e}"
            )
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir)


@router.get("/ui/plans/input_sets/{label}", response_class=HTMLResponse)
def ui_get_input_set_detail(label: str, request: Request):
    try:
        input_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Input set with label '{label}' not found."
        )
    events = (
        list_planning_input_set_events(input_set.id, limit=100) if input_set.id else []
    )

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
        raise HTTPException(
            status_code=404, detail=f"Input set with label '{label}' not found."
        )

    if input_set.status == "archived":
        raise HTTPException(
            status_code=400, detail="Archived input sets cannot be reviewed."
        )

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
        raise HTTPException(
            status_code=404, detail=f"Input set with label '{label}' not found."
        )

    return RedirectResponse(url=f"/ui/plans/input_sets/{label}", status_code=303)


@router.get("/ui/plans/input_sets/{label}/diff", response_class=HTMLResponse)
def ui_plan_input_set_diff(
    label: str,
    request: Request,
    against: str | None = Query(
        None,
        description="Label of the input set to compare against. Defaults to latest ready set.",
    ),
):
    background_tasks = BackgroundTasks()

    try:
        current_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Input set with label '{label}' not found."
        )

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
            other_set = get_planning_input_set(
                label=other_label, include_aggregates=True
            )
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
        elif isinstance(diff_report, dict):
            for section in diff_report.values():
                if not isinstance(section, dict):
                    continue
                rows_added = section.get("added")
                rows_removed = section.get("removed")
                if rows_added is not None:
                    section["added"] = _prepare_delta_rows(
                        rows_added, limit=_DIFF_TABLE_LIMIT
                    )
                if rows_removed is not None:
                    section["removed"] = _prepare_delta_rows(
                        rows_removed, limit=_DIFF_TABLE_LIMIT
                    )

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


@router.get("/ui/plans/{plan_version_id}", response_class=HTMLResponse)
def ui_plan_detail(plan_version_id: int, request: Request):
    plan_version = get_planning_run_detail(plan_version_id)
    if not plan_version:
        raise HTTPException(status_code=404, detail="Plan version not found")

    runs = list_planning_runs(plan_version_id=plan_version_id)

    return templates.TemplateResponse(
        request,
        "plans_detail.html",
        {
            "subtitle": f"Plan: {plan_version.label}",
            "plan_version": plan_version,
            "runs": runs,
        },
    )
