"""PlanRepositoryとファイル保存の共通ヘルパ。

storage_mode (db/files/both) に応じて、PlanRepository書込みとファイル保存を切り替える。
"""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app import db
from core.plan_repository import PlanRepository, PlanRepositoryError
from app.metrics import (
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    PLAN_DB_CAPACITY_TRIM_TOTAL,
    PLAN_DB_LAST_TRIM_TIMESTAMP,
)
from core.plan_repository_builders import (
    PlanKpiRow,
    PlanSeriesRow,
    build_plan_kpis_from_aggregate,
    build_plan_series_from_aggregate,
    build_plan_series_from_detail,
    build_plan_series_from_plan_final,
    build_plan_series_from_weekly_summary,
    build_plan_series_from_mrp,
)


_STORAGE_CHOICES = {"db", "files", "both"}

_PLAN_REPOSITORY = PlanRepository(
    db._conn,
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    PLAN_DB_CAPACITY_TRIM_TOTAL,
    PLAN_DB_LAST_TRIM_TIMESTAMP,
)


def resolve_storage_mode(value: Optional[str] = None) -> str:
    if value:
        mode = str(value).lower()
        if mode in _STORAGE_CHOICES:
            return mode
    env_mode = os.getenv("PLAN_STORAGE_MODE", "both").lower()
    if env_mode in _STORAGE_CHOICES:
        return env_mode
    return "both"


def should_use_db(storage_mode: str) -> bool:
    return storage_mode in {"db", "both"}


def should_use_files(storage_mode: str) -> bool:
    return storage_mode in {"files", "both"}


def write_plan_repository(
    version_id: str,
    *,
    storage_mode: str,
    series: Iterable[PlanSeriesRow],
    kpis: Iterable[PlanKpiRow],
) -> bool:
    if not should_use_db(storage_mode):
        return False
    try:
        _PLAN_REPOSITORY.write_plan(
            version_id, series=series, kpis=kpis, overrides=None
        )
        return True
    except PlanRepositoryError:
        raise


def write_plan_artifacts(
    version_id: Optional[str],
    *,
    storage_mode: str,
    artifacts: Dict[str, Path],
) -> None:
    if not (version_id and should_use_db(storage_mode)):
        return
    for name, path in artifacts.items():
        if not path or not path.exists():
            continue
        db.upsert_plan_artifact(version_id, name, path.read_text(encoding="utf-8"))


def write_json_artifact(
    version_id: Optional[str], name: str, data: dict, *, storage_mode: str
) -> bool:
    if not (version_id and should_use_db(storage_mode)):
        return False
    db.upsert_plan_artifact(
        version_id,
        name,
        json.dumps(data, ensure_ascii=False),
    )
    return True


def write_json_output(path: Path, data: dict, *, storage_mode: str) -> None:
    if not should_use_files(storage_mode):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_aggregate_series(
    version_id: str, data: Dict[str, Any]
) -> List[PlanSeriesRow]:
    return build_plan_series_from_aggregate(version_id, data)


def build_aggregate_kpis(version_id: str, data: Dict[str, Any]) -> List[PlanKpiRow]:
    return build_plan_kpis_from_aggregate(version_id, data)


def write_aggregate_result(
    *,
    version_id: Optional[str],
    data: Dict[str, Any],
    output_path: Path,
    storage_mode: str,
) -> bool:
    rows: List[Dict[str, Any]] = list(data.get("rows") or [])
    write_json_output(output_path, data, storage_mode=storage_mode)
    if version_id and should_use_db(storage_mode) and rows:
        series = build_aggregate_series(version_id, data)
        kpis = build_aggregate_kpis(version_id, data)
        write_plan_repository(
            version_id,
            storage_mode=storage_mode,
            series=series,
            kpis=kpis,
        )
        return True
    return False


def write_allocate_result(
    *,
    version_id: Optional[str],
    aggregate_data: Dict[str, Any] | None,
    detail_data: Dict[str, Any],
    output_path: Path,
    storage_mode: str,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> bool:
    detail_rows: List[Dict[str, Any]] = list(detail_data.get("rows") or [])
    write_json_output(output_path, detail_data, storage_mode=storage_mode)
    if not version_id or not should_use_db(storage_mode):
        return False

    has_detail = bool(detail_rows)
    has_aggregate = bool(aggregate_data and aggregate_data.get("rows"))
    if not has_detail and not has_aggregate:
        return False

    series: List[PlanSeriesRow] = []
    if has_aggregate:
        series.extend(
            build_plan_series_from_aggregate(
                version_id,
                aggregate_data,
                default_location_key=default_location_key,
                default_location_type=default_location_type,
            )
        )
    if has_detail:
        series.extend(
            build_plan_series_from_detail(
                version_id,
                detail_data,
                default_location_key=default_location_key,
                default_location_type=default_location_type,
            )
        )

    kpis: List[PlanKpiRow] = []
    if has_aggregate:
        kpis = build_plan_kpis_from_aggregate(version_id, aggregate_data)

    write_plan_repository(
        version_id,
        storage_mode=storage_mode,
        series=series,
        kpis=kpis,
    )
    return True


def write_mrp_result(
    *,
    version_id: Optional[str],
    mrp_data: Dict[str, Any],
    output_path: Path,
    storage_mode: str,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> bool:
    list(mrp_data.get("rows") or [])
    write_json_output(output_path, mrp_data, storage_mode=storage_mode)
    if not version_id or not should_use_db(storage_mode):
        return False

    series = build_plan_series_from_mrp(
        version_id,
        mrp_data,
        default_location_key=default_location_key,
        default_location_type=default_location_type,
    )

    try:
        _PLAN_REPOSITORY.replace_plan_series_level(version_id, "mrp", series)
    except PlanRepositoryError:
        raise
    return bool(series)


def write_plan_final_result(
    *,
    version_id: Optional[str],
    plan_final_data: Dict[str, Any],
    output_path: Path,
    storage_mode: str,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> bool:
    write_json_output(output_path, plan_final_data, storage_mode=storage_mode)
    if not version_id or not should_use_db(storage_mode):
        return False

    detail_series = build_plan_series_from_plan_final(
        version_id,
        plan_final_data,
        default_location_key=default_location_key,
        default_location_type=default_location_type,
    )
    weekly_series = build_plan_series_from_weekly_summary(
        version_id,
        plan_final_data,
        default_location_key=default_location_key,
        default_location_type=default_location_type,
    )

    try:
        _PLAN_REPOSITORY.replace_plan_series_level(
            version_id, "mrp_final", detail_series
        )
        _PLAN_REPOSITORY.replace_plan_series_level(
            version_id, "weekly_summary", weekly_series
        )
    except PlanRepositoryError:
        raise
    return bool(detail_series or weekly_series)


def write_anchor_adjust_result(
    *,
    version_id: Optional[str],
    adjusted_data: Dict[str, Any],
    output_path: Path,
    storage_mode: str,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> bool:
    write_json_output(output_path, adjusted_data, storage_mode=storage_mode)
    if not version_id or not should_use_db(storage_mode):
        return False

    series = build_plan_series_from_detail(
        version_id,
        adjusted_data,
        default_location_key=default_location_key,
        default_location_type=default_location_type,
        level="det_adjusted",
    )
    try:
        _PLAN_REPOSITORY.replace_plan_series_level(version_id, "det_adjusted", series)
    except PlanRepositoryError:
        raise
    return bool(series)


def write_reconcile_log_result(
    *,
    version_id: Optional[str],
    log_data: Dict[str, Any],
    output_path: Path,
    storage_mode: str,
    artifact_name: str,
) -> bool:
    write_json_output(output_path, log_data, storage_mode=storage_mode)
    return write_json_artifact(
        version_id,
        artifact_name,
        log_data,
        storage_mode=storage_mode,
    )


def write_report_csv_result(
    *,
    version_id: Optional[str],
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
    output_path: Path,
    storage_mode: str,
    artifact_name: str,
) -> bool:
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    csv_text = csv_buffer.getvalue()

    if should_use_files(storage_mode):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as f:
            f.write(csv_text)

    return write_json_artifact(
        version_id,
        artifact_name,
        {"type": "csv", "content": csv_text},
        storage_mode=storage_mode,
    )
