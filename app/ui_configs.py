from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api import app
from app.db import (
    get_plan_artifact,
    list_plan_versions,
)
from app.utils import ms_to_jst_str
from core.config import (
    CanonicalConfig,
    CanonicalConfigNotFoundError,
    CanonicalVersionSummary,
    diff_canonical_configs,
    list_canonical_version_summaries,
    load_canonical_config_from_db,
    save_canonical_config,
    validate_canonical_config,
    delete_canonical_config,
)

_BASE_DIR = Path(__file__).resolve().parents[1]

templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


def _format_time(value: Any) -> str:
    try:
        return ms_to_jst_str(value)
    except Exception:
        return ""


def _summarize_counts(config: CanonicalConfig) -> Dict[str, int]:
    keys = (
        "items",
        "nodes",
        "arcs",
        "bom",
        "demands",
        "capacities",
        "calendars",
        "hierarchies",
    )
    return {key: len(getattr(config, key)) for key in keys}


def _sample_records(records: List[Any], limit: int = 8) -> List[Dict[str, Any]]:
    sample = []
    for obj in records[:limit]:
        if hasattr(obj, "model_dump"):
            sample.append(obj.model_dump(mode="json"))
        else:
            sample.append(obj)
    return sample


def _group_validation(result) -> Dict[str, List[Dict[str, Any]]]:
    grouped = {"errors": [], "warnings": []}
    if not result:
        return grouped
    for issue in result.issues:
        payload = {
            "code": issue.code,
            "message": issue.message,
            "context": issue.context or {},
        }
        if issue.severity == "error":
            grouped["errors"].append(payload)
        else:
            grouped["warnings"].append(payload)
    return grouped


def _render_import_template(
    request: Request,
    *,
    error: str | None = None,
    warning: str | None = None,
    json_text: str = "",
    plan_version_id: str = "",
    validation_messages: Dict[str, List[Dict[str, Any]]] | None = None,
    status_code: int = 200,
):
    plan_versions = [
        {
            **plan,
            "created_at_str": _format_time(plan.get("created_at")),
        }
        for plan in list_plan_versions(limit=20)
    ]
    return templates.TemplateResponse(
        request,
        "configs_canonical_import.html",
        {
            "subtitle": "Import Canonical Configuration",
            "error": error,
            "warning": warning,
            "json_text": json_text,
            "plan_version_id": plan_version_id,
            "validation_messages": validation_messages
            or {"errors": [], "warnings": []},
            "plan_versions": plan_versions,
        },
        status_code=status_code,
    )


@app.get("/ui/configs", response_class=HTMLResponse)
def ui_configs_list(request: Request):
    sample_files_dir = _BASE_DIR / "samples" / "canonical"
    sample_files = [
        f.name for f in sample_files_dir.glob("*.json") if f.is_file()
    ]

    canonical_summaries: List[CanonicalVersionSummary] = (
        list_canonical_version_summaries(limit=30, include_deleted=False)
    )
    canonical_rows: List[Dict[str, Any]] = []
    for summary in canonical_summaries:
        meta_dict = summary.meta.model_dump()
        meta_dict["created_at_str"] = _format_time(meta_dict.get("created_at"))
        meta_dict["updated_at_str"] = _format_time(meta_dict.get("updated_at"))
        canonical_rows.append({"meta": meta_dict, "counts": summary.counts})

    diff_options = [
        {
            "id": row["meta"].get("version_id"),
            "name": row["meta"].get("name"),
            "status": row["meta"].get("status"),
        }
        for row in canonical_rows
        if row["meta"].get("version_id") is not None
    ]

    return templates.TemplateResponse(
        request,
        "configs_list.html",
        {
            "subtitle": "Configuration Management",
            "canonical_rows": canonical_rows,
            "diff_options": diff_options,
            "sample_files": sample_files,
        },
    )


@app.get("/ui/configs/canonical")
def ui_canonical_configs_redirect():
    return RedirectResponse(url="/ui/configs", status_code=307)


@app.get("/ui/configs/canonical/import", response_class=HTMLResponse)
def ui_canonical_config_import(request: Request):
    return _render_import_template(request)


@app.get("/ui/configs/canonical/diff", response_class=HTMLResponse)
def ui_canonical_config_diff(
    request: Request, base_id: int = Query(...), compare_id: int = Query(...)
):
    summaries = list_canonical_version_summaries(limit=30)
    diff_options = [
        {
            "id": s.meta.version_id,
            "name": s.meta.name,
            "status": s.meta.status,
        }
        for s in summaries
        if s.meta.version_id is not None
    ]

    if base_id == compare_id:
        return templates.TemplateResponse(
            request,
            "configs_canonical_diff.html",
            {
                "subtitle": "Canonical Configuration Diff",
                "error": "Selected versions are identical. Choose another version.",
                "diff_options": diff_options,
                "base_meta": {},
                "compare_meta": {},
                "diff": {"meta": {}, "entities": {}},
                "base_id": base_id,
                "compare_id": compare_id,
            },
            status_code=400,
        )
    try:
        base_config, _ = load_canonical_config_from_db(base_id, validate=False)
        compare_config, _ = load_canonical_config_from_db(compare_id, validate=False)
    except CanonicalConfigNotFoundError:
        raise HTTPException(status_code=404, detail="canonical config not found")

    diff = diff_canonical_configs(base_config, compare_config)
    base_meta = base_config.meta.model_dump()
    compare_meta = compare_config.meta.model_dump()
    base_meta["created_at_str"] = _format_time(base_meta.get("created_at"))
    base_meta["updated_at_str"] = _format_time(base_meta.get("updated_at"))
    compare_meta["created_at_str"] = _format_time(compare_meta.get("created_at"))
    compare_meta["updated_at_str"] = _format_time(compare_meta.get("updated_at"))

    return templates.TemplateResponse(
        request,
        "configs_canonical_diff.html",
        {
            "subtitle": "Canonical Configuration Diff",
            "base_meta": base_meta,
            "compare_meta": compare_meta,
            "diff": diff,
            "diff_options": diff_options,
            "base_id": base_id,
            "compare_id": compare_id,
        },
    )


@app.post("/ui/configs/canonical/sample")
def ui_canonical_config_seed_sample(sample_file: str = Form(...)):
    sample_path = _BASE_DIR / "samples" / "canonical" / sample_file
    if not sample_path.exists():
        raise HTTPException(status_code=404, detail=f"Canonical sample '{sample_file}' not found")

    try:
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse canonical sample JSON: {exc}",
        )

    try:
        config = CanonicalConfig.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to validate canonical sample JSON: {exc}",
        )

    config.meta.attributes.setdefault("ui_import", {})
    config.meta.attributes["ui_import"].update(
        {
            "source": "sample",
            "path": str(sample_path.relative_to(_BASE_DIR)),
        }
    )

    validation = validate_canonical_config(config)
    if validation and validation.has_errors:
        messages = ", ".join(
            f"{issue.code}: {issue.message}" for issue in validation.issues
        )
        raise HTTPException(
            status_code=500,
            detail=f"Consistency check for canonical sample failed: {messages}",
        )

    version_id = save_canonical_config(config)
    return RedirectResponse(url=f"/ui/configs/canonical/{version_id}", status_code=303)


@app.get("/ui/configs/canonical/{version_id}", response_class=HTMLResponse)
def ui_canonical_config_detail(request: Request, version_id: int):
    try:
        config, validation = load_canonical_config_from_db(version_id, validate=True)
    except CanonicalConfigNotFoundError:
        raise HTTPException(status_code=404, detail="canonical config not found")

    meta = config.meta.model_dump()
    meta["created_at_str"] = _format_time(meta.get("created_at"))
    meta["updated_at_str"] = _format_time(meta.get("updated_at"))
    counts = _summarize_counts(config)
    samples = {
        "items": _sample_records(config.items, limit=8),
        "nodes": _sample_records(config.nodes, limit=5),
        "arcs": _sample_records(config.arcs, limit=5),
        "bom": _sample_records(config.bom, limit=5),
        "demands": _sample_records(config.demands, limit=5),
        "capacities": _sample_records(config.capacities, limit=5),
        "calendars": _sample_records(config.calendars, limit=3),
        "hierarchies": _sample_records(config.hierarchies, limit=5),
    }
    samples_json = {
        key: json.dumps(value, ensure_ascii=False, indent=2)
        for key, value in samples.items()
    }
    validation_messages = _group_validation(validation)

    summaries = list_canonical_version_summaries(limit=30)
    diff_options = [
        {
            "id": s.meta.version_id,
            "name": s.meta.name,
            "status": s.meta.status,
        }
        for s in summaries
        if s.meta.version_id is not None and s.meta.version_id != version_id
    ]

    preview_json = config.model_dump(mode="json")
    preview_text = json.dumps(preview_json, ensure_ascii=False, indent=2)
    truncated = False
    if len(preview_text) > 6000:
        preview_text = preview_text[:6000] + "\n... (truncated)"
        truncated = True

    return templates.TemplateResponse(
        request,
        "configs_canonical_detail.html",
        {
            "subtitle": "Canonical Configuration Detail",
            "meta": meta,
            "counts": counts,
            "samples_json": samples_json,
            "validation_messages": validation_messages,
            "diff_options": diff_options,
            "version_id": version_id,
            "preview_text": preview_text,
            "preview_truncated": truncated,
        },
    )


@app.post("/ui/configs/canonical/{version_id}/delete")
def ui_canonical_config_delete(version_id: int):
    try:
        delete_canonical_config(version_id)
    except CanonicalConfigNotFoundError:
        raise HTTPException(status_code=404, detail="canonical config not found")
    return RedirectResponse(url="/ui/configs", status_code=303)


@app.get("/ui/configs/canonical/{version_id}/json")
def ui_canonical_config_download(version_id: int):
    try:
        config, _ = load_canonical_config_from_db(version_id, validate=False)
    except CanonicalConfigNotFoundError:
        raise HTTPException(status_code=404, detail="canonical config not found")
    data = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2)
    filename = f"canonical_config_{version_id}.json"
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/ui/configs/canonical/import/json")
async def ui_canonical_config_import_json(
    request: Request,
    name: str = Form(...),
    status: str = Form("draft"),
    json_text: str = Form(""),
    file: UploadFile | None = File(None),
):
    raw_text = (json_text or "").strip()
    if file and file.filename:
        raw_text = (await file.read()).decode("utf-8")

    if not raw_text:
        return _render_import_template(
            request,
            error="JSON payload is empty. Provide a file or paste JSON text.",
            status_code=400,
        )

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return _render_import_template(
            request,
            error=f"Failed to parse JSON: {exc}",
            json_text=raw_text,
            status_code=400,
        )

    try:
        config = CanonicalConfig.model_validate(payload)
    except ValidationError as exc:
        return _render_import_template(
            request,
            error="Input is not a valid CanonicalConfig structure.",
            json_text=raw_text,
            validation_messages={
                "errors": [
                    {"code": err.get("type"), "message": str(err.get("msg"))}
                    for err in exc.errors()
                ],
                "warnings": [],
            },
            status_code=400,
        )

    if name:
        config.meta.name = name
    if status:
        config.meta.status = status
    config.meta.attributes.setdefault("ui_import", {})
    config.meta.attributes["ui_import"].update(
        {
            "source": "json",
            "filename": file.filename if file else None,
        }
    )

    validation = validate_canonical_config(config)
    if validation and validation.has_errors:
        return _render_import_template(
            request,
            error="Consistency check reported errors. Review the details below.",
            json_text=raw_text,
            validation_messages=_group_validation(validation),
            status_code=400,
        )

    version_id = save_canonical_config(config)
    return RedirectResponse(url=f"/ui/configs/canonical/{version_id}", status_code=303)


@app.post("/ui/configs/canonical/import/plan")
def ui_canonical_config_import_plan(
    request: Request,
    plan_version_id: str = Form(...),
    name: str = Form(""),
    status: str = Form("draft"),
):
    snapshot = get_plan_artifact(plan_version_id, "canonical_snapshot.json")
    if not snapshot:
        return _render_import_template(
            request,
            error=f"Plan {plan_version_id} does not contain canonical_snapshot.json.",
            plan_version_id=plan_version_id,
            status_code=404,
        )

    try:
        config = CanonicalConfig.model_validate(snapshot)
    except ValidationError:
        return _render_import_template(
            request,
            error="Failed to load canonical snapshot from plan artifacts. Check JSON structure.",
            plan_version_id=plan_version_id,
            status_code=400,
        )

    if name:
        config.meta.name = name
    if status:
        config.meta.status = status
    config.meta.attributes.setdefault("ui_import", {})
    config.meta.attributes["ui_import"].update(
        {
            "source": "plan",
            "plan_version_id": plan_version_id,
        }
    )

    validation = validate_canonical_config(config)
    if validation and validation.has_errors:
        return _render_import_template(
            request,
            error="Consistency check reported errors. Verify the plan artifact content.",
            plan_version_id=plan_version_id,
            validation_messages=_group_validation(validation),
            status_code=400,
        )

    version_id = save_canonical_config(config)
    return RedirectResponse(url=f"/ui/configs/canonical/{version_id}", status_code=303)
