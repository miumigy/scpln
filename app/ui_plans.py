import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import db
from app.run_registry_db import table_exists
from app.metrics import (
    INPUT_SET_DIFF_CACHE_HITS_TOTAL,
    INPUT_SET_DIFF_CACHE_STALE_TOTAL,
    INPUT_SET_DIFF_JOBS_TOTAL,
)
from app.template_filters import register_format_filters
from app.utils import format_datetime, ms_to_jst_str
from core.config.storage import (
    get_planning_input_set,
    list_canonical_version_summaries,
    list_planning_input_set_events,
    list_planning_input_sets,
    log_planning_input_set_event,
    PlanningInputSetNotFoundError,
    update_planning_input_set,
)
from core.sorting import natural_sort_key
from core.config.importer import import_planning_inputs
from core.plan_repository import PlanRepository

router = APIRouter()
templates = Jinja2Templates(directory="templates")
register_format_filters(templates)

_BASE_DIR = Path(__file__).resolve().parent.parent
_DIFF_TABLE_LIMIT = 100
_PLAN_STATE_STEPS = ["draft", "aggregated", "disaggregated", "scheduled", "executed"]
_PLAN_REPOSITORY: PlanRepository | None = None


def _form_value(form, name: str) -> str | None:
    val = form.get(name)
    if val is None:
        return None
    if isinstance(val, str):
        text = val.strip()
        return text or None
    return str(val)


def _form_int(form, name: str) -> int | None:
    value = _form_value(form, name)
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _form_float(form, name: str) -> float | None:
    value = _form_value(form, name)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _checkbox_checked(form, name: str) -> bool:
    value = form.get(name)
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "off")
    return bool(value)


def _extract_plan_options(form) -> dict[str, object]:
    opts: dict[str, object] = {}
    opts["version_id"] = _form_value(form, "version_id")
    opts["config_version_id"] = _form_int(form, "config_version_id")
    opts["base_scenario_id"] = _form_int(form, "base_scenario_id")
    opts["input_set_label"] = _form_value(form, "input_set_label")
    opts["weeks"] = _form_int(form, "weeks") or 4
    opts["lt_unit"] = _form_value(form, "lt_unit") or "day"
    opts["round_mode"] = _form_value(form, "round_mode") or "int"
    opts["cutover_date"] = _form_value(form, "cutover_date")
    opts["recon_window_days"] = _form_int(form, "recon_window_days")
    opts["anchor_policy"] = _form_value(form, "anchor_policy")
    opts["calendar_mode"] = _form_value(form, "calendar_mode")
    opts["carryover"] = _form_value(form, "carryover")
    opts["carryover_split"] = _form_float(form, "carryover_split")
    opts["apply_adjusted"] = _checkbox_checked(form, "apply_adjusted")
    opts["tol_abs"] = _form_float(form, "tol_abs")
    opts["tol_rel"] = _form_float(form, "tol_rel")
    opts["max_adjust_ratio"] = _form_float(form, "max_adjust_ratio")
    opts["blend_split_next"] = _form_float(form, "blend_split_next")
    opts["blend_weight_mode"] = _form_value(form, "blend_weight_mode")
    opts["lightweight"] = _checkbox_checked(form, "lightweight")
    return opts


def _raise_from_json_response(resp: JSONResponse) -> None:
    detail: str | dict[str, object] | None = None
    try:
        payload = json.loads(resp.body.decode("utf-8"))
        detail = payload.get("detail") if isinstance(payload, dict) else payload
    except Exception:
        try:
            detail = resp.body.decode("utf-8", errors="ignore")
        except Exception:
            detail = None
    raise HTTPException(status_code=resp.status_code, detail=detail or "request failed")


def _get_plan_repository() -> PlanRepository:
    global _PLAN_REPOSITORY
    if _PLAN_REPOSITORY is None:
        _PLAN_REPOSITORY = PlanRepository(db._conn)
    return _PLAN_REPOSITORY


def _normalize_plan_state(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    state = dict(raw)
    status = state.get("state") or state.get("status") or "draft"
    if status not in _PLAN_STATE_STEPS:
        status = "draft"
    state["state"] = status
    state["status"] = status
    state.setdefault("display_status", status)
    timestamp = (
        state.get("updated_at")
        or state.get("timestamp")
        or state.get("submitted_at")
        or state.get("approved_at")
    )
    if timestamp is not None:
        try:
            ts = int(timestamp)
            if ts < 1_000_000_000_000:
                ts *= 1000
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            state["display_time"] = dt.isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    invalid = state.get("invalid")
    if invalid is None:
        state["invalid"] = []
    elif not isinstance(invalid, list):
        state["invalid"] = [invalid]
    state.setdefault("source", state.get("source") or "ui")
    return state


def _list_plan_runs(version_id: str, *, limit: int = 10):
    """指定PlanVersionに紐づく直近のRun一覧をDBから取得する。"""
    plan_runs: list[dict[str, str | int | None]] = []
    plan_run_ids: list[str] = []
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT run_id, summary, started_at FROM runs WHERE plan_version_id=? ORDER BY started_at DESC, run_id DESC LIMIT ?",
            (version_id, limit),
        ).fetchall()
    for row in rows:
        summary: dict[str, str | int | float | None] = {}
        try:
            summary = json.loads(row["summary"] or "{}")
        except Exception:
            summary = {}
        plan_runs.append(
            {
                "run_id": row["run_id"],
                "started_at": row["started_at"],
                "started_at_str": ms_to_jst_str(row["started_at"]),
                "fill_rate": summary.get("fill_rate"),
                "profit_total": summary.get("profit_total"),
            }
        )
        plan_run_ids.append(row["run_id"])
    return plan_runs, plan_run_ids


def _diff_cache_paths(label: str, other_label: str) -> tuple[Path, Path]:
    base_dir = _BASE_DIR / "tmp" / "input_set_diffs"
    base_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{label}__{other_label}.json"
    cache_path = base_dir / filename
    lock_path = base_dir / f"{label}__{other_label}.lock"
    return cache_path, lock_path


def _is_lock_active(lock_path: Path) -> bool:
    if not lock_path.exists():
        return False
    try:
        if time.time() - lock_path.stat().st_mtime > 120:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            return False
    except Exception:
        return lock_path.exists()
    return True


def _load_cached_diff(cache_path: Path) -> tuple[dict | None, int | None]:
    if not cache_path.exists():
        INPUT_SET_DIFF_CACHE_STALE_TOTAL.inc()
        return None, None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("diff payload is not a dict")
        timestamp = int(cache_path.stat().st_mtime * 1000)
        INPUT_SET_DIFF_CACHE_HITS_TOTAL.inc()
        return payload, timestamp
    except Exception:
        logging.exception("input_set_diff_cache_invalid", extra={"path": str(cache_path)})
        INPUT_SET_DIFF_CACHE_STALE_TOTAL.inc()
        return None, None


def _prepare_delta_rows(rows: list[dict], *, limit: int | None = None) -> list[dict]:
    if not rows:
        return []

    def _sort_key(row: dict) -> tuple:
        primary = row.get("period") or row.get("week") or row.get("time_bucket_key") or ""
        secondary = row.get("family") or row.get("sku") or row.get("item_key") or ""
        return (natural_sort_key(primary), natural_sort_key(secondary))

    sorted_rows = sorted(rows, key=_sort_key)
    if limit is not None and limit >= 0:
        return sorted_rows[:limit]
    return sorted_rows


def _schedule_diff_generation(
    background_tasks: BackgroundTasks,
    label: str,
    other_label: str,
    cache_path: Path,
    lock_path: Path,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_path.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass

    def _run_diff_job() -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="diff-"))
        try:
            script_path = _BASE_DIR / "scripts" / "export_planning_inputs.py"
            cmd = [
                sys.executable,
                str(script_path),
                "--label",
                label,
                "--diff-against",
                other_label,
                "-o",
                str(temp_dir),
            ]
            proc = subprocess.run(
                cmd,
                cwd=str(_BASE_DIR),
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                logging.error(
                    "input_set_diff_job_failed",
                    extra={
                        "label": label,
                        "other_label": other_label,
                        "stderr": proc.stderr,
                    },
                )
                INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
                return
            diff_file = temp_dir / "diff_report.json"
            if not diff_file.exists():
                logging.error(
                    "input_set_diff_job_missing_report",
                    extra={"label": label, "other_label": other_label},
                )
                INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
                return
            shutil.copy(diff_file, cache_path)
            INPUT_SET_DIFF_JOBS_TOTAL.labels(result="success").inc()
        except Exception:
            logging.exception("input_set_diff_job_crashed")
            INPUT_SET_DIFF_JOBS_TOTAL.labels(result="failure").inc()
        finally:
            try:
                lock_path.unlink()
            except Exception:
                pass
            shutil.rmtree(temp_dir, ignore_errors=True)

    background_tasks.add_task(_run_diff_job)


@router.post("/ui/plans/create_and_execute", response_class=HTMLResponse)
async def ui_plans_create_and_execute(request: Request):
    form = await request.form()
    options = _extract_plan_options(form)
    config_version_id = options.get("config_version_id")
    if not config_version_id:
        raise HTTPException(
            status_code=400, detail="config_version_id is required to create a plan"
        )
    options.setdefault("lightweight", True)
    payload = {
        "pipeline": "integrated",
        "async": True,
        "options": options,
    }
    from app import runs_api as runs_api_module

    result = runs_api_module.post_runs(payload)
    if isinstance(result, JSONResponse):
        _raise_from_json_response(result)
    location = result.get("location")
    if not location:
        raise HTTPException(
            status_code=500, detail="Job location was not provided by /runs"
        )
    return RedirectResponse(url=location, status_code=303)


@router.post("/ui/plans/{plan_version_id}/execute_auto", response_class=HTMLResponse)
async def ui_plans_execute_auto(plan_version_id: str, request: Request):
    version_id = str(plan_version_id)
    version = db.get_plan_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Plan version not found")

    form = await request.form()
    options = _extract_plan_options(form)
    config_version_id = (
        options.get("config_version_id") or version.get("config_version_id")
    )
    if not config_version_id:
        raise HTTPException(
            status_code=400,
            detail="config_version_id is not available for this plan",
        )
    options["config_version_id"] = config_version_id
    options["base_scenario_id"] = (
        options.get("base_scenario_id") or version.get("base_scenario_id")
    )
    options["input_set_label"] = (
        options.get("input_set_label") or version.get("input_set_label")
    )
    if not options.get("version_id"):
        options["version_id"] = f"{version_id}-auto-{int(time.time())}"
    options["lightweight"] = True

    from app import plans_api as plans_api_module

    result = plans_api_module.post_plans_create_and_execute(options)
    if isinstance(result, JSONResponse):
        _raise_from_json_response(result)
    new_version_id = result.get("version_id") or options["version_id"]
    return RedirectResponse(url=f"/ui/plans/{new_version_id}", status_code=303)


class PlanningRunForm(BaseModel):
    plan_version_id: int = Field(..., description="計画バージョンID")
    label: str = Field(..., description="実行ラベル")


def _fetch_plan_rows(limit: int = 50, offset: int = 0):
    plans = db.list_plan_versions(limit=limit, offset=offset)
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
            logging.warning(f"Failed to parse meta.json for sample: {d.name}", exc_info=True)
    return sorted(samples, key=lambda x: x["name"])


@router.post("/ui/plans/input_sets/sample", response_class=HTMLResponse)
async def ui_post_load_sample_input_set(request: Request, sample_name: str = Form(...)):
    """Load a predefined sample input set into the database."""
    error_url = "/ui/plans/input_sets?error="
    sample_dir = _BASE_DIR / "samples" / "planning_input_sets" / sample_name
    if not sample_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Sample '{sample_name}' not found.")

    meta_path = sample_dir / "meta.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail=f"meta.json for sample '{sample_name}' not found.")

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        label = meta.get("label")
        canonical_sample_name = meta.get("canonical_sample_name")
        if not label or not canonical_sample_name:
            return RedirectResponse(url=error_url + "Invalid_meta_json", status_code=303)

        # Find the corresponding canonical config version ID
        config_version_id = None
        summaries = list_canonical_version_summaries(limit=1000)
        for summary in summaries:
            if summary.meta.path and summary.meta.path.endswith(canonical_sample_name):
                config_version_id = summary.meta.version_id
                break
        
        if not config_version_id:
            return RedirectResponse(url=error_url + f"Canonical_config_for_{canonical_sample_name}_not_found", status_code=303)

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
            return RedirectResponse(url=error_url + result.get("message", "Import_failed"), status_code=303)

        return RedirectResponse(url=f"/ui/plans/input_sets/{label}", status_code=303)

    except Exception as e:
        logging.exception("Failed to load sample input set.")
        return RedirectResponse(url=error_url + f"Internal_error_{e}", status_code=303)


@router.get("/ui/plans/input_sets", response_class=HTMLResponse)
@router.get("/ui/input_sets", response_class=HTMLResponse)
def ui_list_input_sets(request: Request):
    status_query = (request.query_params.get("status") or "ready").lower()
    status_filter = None if status_query == "all" else status_query
    input_sets = list_planning_input_sets(status=status_filter)
    for item in input_sets:
        setattr(item, "created_at_str", format_datetime(getattr(item, "created_at", None)))
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
    from app.config_api import _list_canonical_options

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
        elif isinstance(diff_report, dict):
            for section in diff_report.values():
                if not isinstance(section, dict):
                    continue
                rows_added = section.get("added")
                rows_removed = section.get("removed")
                if rows_added is not None:
                    section["added"] = _prepare_delta_rows(rows_added, limit=_DIFF_TABLE_LIMIT)
                if rows_removed is not None:
                    section["removed"] = _prepare_delta_rows(rows_removed, limit=_DIFF_TABLE_LIMIT)

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
def ui_plan_detail(plan_version_id: str, request: Request):
    version_id = str(plan_version_id)
    version = db.get_plan_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Plan version not found")

    plan_runs, plan_run_ids = _list_plan_runs(version_id)

    related_plans = []
    base_scenario_id = version.get("base_scenario_id")
    if base_scenario_id is not None:
        related_plans = db.list_plan_versions_by_base(base_scenario_id, limit=5)
        related_plans = [
            p for p in related_plans if str(p.get("version_id")) != version_id
        ]

    context_config_version_id = version.get("config_version_id")

    plan_state = _normalize_plan_state(
        db.get_plan_artifact(version_id, "state.json") or None
    )

    return templates.TemplateResponse(
        request,
        "plans_detail.html",
        {
            "subtitle": f"Plan: {version_id}",
            "version": version,
            "version_id": version_id,
            "config_version_id": context_config_version_id,
            "plan_runs": plan_runs,
            "plan_run_ids": plan_run_ids,
            "plan_state": plan_state,
            "canonical_meta": None,
            "canonical_counts": None,
            "related_plans": related_plans,
        },
    )


@router.post("/ui/plans/{plan_version_id}/state/advance", response_class=HTMLResponse)
def ui_plan_state_advance(plan_version_id: str, to: str = Form(...)):
    version_id = str(plan_version_id)
    version = db.get_plan_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Plan version not found")
    target = (to or "").strip()
    if target not in _PLAN_STATE_STEPS:
        target = "draft"
    state = db.get_plan_artifact(version_id, "state.json") or {
        "state": version.get("status") or "draft",
        "invalid": [],
    }
    current = state.get("state") or "draft"
    if current not in _PLAN_STATE_STEPS:
        current = "draft"
    if _PLAN_STATE_STEPS.index(target) < _PLAN_STATE_STEPS.index(current):
        target = current
    invalid = [
        step
        for step in state.get("invalid") or []
        if step in _PLAN_STATE_STEPS
        and _PLAN_STATE_STEPS.index(step) > _PLAN_STATE_STEPS.index(target)
    ]
    state.update(
        {
            "state": target,
            "status": target,
            "display_status": target,
            "invalid": invalid,
            "updated_at": int(time.time() * 1000),
            "actor": "ui_plan_state",
            "source": "ui",
        }
    )
    db.upsert_plan_artifact(
        version_id, "state.json", json.dumps(state, ensure_ascii=False)
    )
    try:
        db.update_plan_version(version_id, status=target)
    except Exception:
        logging.exception(
            "ui_plan_state_update_failed", extra={"version_id": version_id}
        )
    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


@router.post("/ui/plans/{plan_version_id}/state/invalidate", response_class=HTMLResponse)
def ui_plan_state_invalidate(plan_version_id: str, from_step: str = Form(...)):
    version_id = str(plan_version_id)
    version = db.get_plan_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Plan version not found")
    step = (from_step or "").strip()
    if step not in _PLAN_STATE_STEPS:
        step = "draft"
    idx = _PLAN_STATE_STEPS.index(step)
    state = {
        "state": step,
        "status": step,
        "display_status": step,
        "invalid": _PLAN_STATE_STEPS[idx + 1 :],
        "updated_at": int(time.time() * 1000),
        "actor": "ui_plan_state",
        "source": "ui",
    }
    db.upsert_plan_artifact(
        version_id, "state.json", json.dumps(state, ensure_ascii=False)
    )
    try:
        db.update_plan_version(version_id, status=step)
    except Exception:
        logging.exception(
            "ui_plan_state_invalidate_update_failed",
            extra={"version_id": version_id},
        )
    return RedirectResponse(url=f"/ui/plans/{version_id}", status_code=303)


@router.post("/ui/plans/{plan_version_id}/delete", response_class=HTMLResponse)
def ui_plan_delete(plan_version_id: str):
    version_id = str(plan_version_id)
    version = db.get_plan_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Plan version not found")

    try:
        _get_plan_repository().delete_plan(version_id)
    except Exception:
        logging.exception(
            "ui_plan_delete_repository_failed", extra={"version_id": version_id}
        )
    for cleanup in (
        db.delete_plan_artifacts,
        db.delete_plan_version,
        db.clear_plan_version_from_runs,
    ):
        try:
            cleanup(version_id)
        except Exception:
            logging.exception(
                "ui_plan_delete_cleanup_failed",
                extra={"version_id": version_id, "op": cleanup.__name__},
            )
    return RedirectResponse(url="/ui/plans", status_code=303)
