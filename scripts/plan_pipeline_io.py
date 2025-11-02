"""Planningパイプライン用の共通I/Oユーティリティ。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List, Union

from scripts.plan_storage import (
    resolve_storage_mode,
    should_use_db,
    should_use_files,
    write_allocate_result,
    write_aggregate_result,
    write_mrp_result,
    write_plan_final_result,
    write_anchor_adjust_result,
    write_reconcile_log_result,
    write_report_csv_result,
)


@dataclass(slots=True)
class PlanStorageConfig:
    """CLI経由でのPlan保存設定を保持するデータクラス。"""

    storage_mode: str
    version_id: Optional[str]
    default_location_key: str = "global"
    default_location_type: str = "global"

    @property
    def use_db(self) -> bool:
        return should_use_db(self.storage_mode)

    @property
    def use_files(self) -> bool:
        return should_use_files(self.storage_mode)


def resolve_storage_config(
    storage_option: Optional[str],
    version_id: Optional[str],
    *,
    cli_label: str,
    default_location_key: str = "global",
    default_location_type: str = "global",
) -> Tuple[PlanStorageConfig, Optional[str]]:
    """CLI引数から保存設定を生成し、必要なら警告メッセージを返す。"""

    storage_mode = resolve_storage_mode(storage_option)
    warning: Optional[str] = None
    final_version = version_id
    if should_use_db(storage_mode) and not version_id:
        warning = (
            f"[{cli_label}] storage_mode includes 'db' but --version-id is missing. "
            "Falling back to files only."
        )
        storage_mode = "files"
        final_version = None

    config = PlanStorageConfig(
        storage_mode=storage_mode,
        version_id=final_version,
        default_location_key=default_location_key,
        default_location_type=default_location_type,
    )
    return config, warning


def store_aggregate_payload(
    config: PlanStorageConfig, *, data: Dict[str, Any], output_path: Path
) -> bool:
    """plan_aggregateの出力を保存する。戻り値はDBへ書いたか否か。"""

    return write_aggregate_result(
        version_id=config.version_id,
        data=data,
        output_path=output_path,
        storage_mode=config.storage_mode,
    )


def store_allocate_payload(
    config: PlanStorageConfig,
    *,
    aggregate_data: Dict[str, Any] | None,
    detail_data: Dict[str, Any],
    output_path: Path,
) -> bool:
    """allocateの出力と既存aggregateデータを保存する。"""

    return write_allocate_result(
        version_id=config.version_id,
        aggregate_data=aggregate_data,
        detail_data=detail_data,
        output_path=output_path,
        storage_mode=config.storage_mode,
        default_location_key=config.default_location_key,
        default_location_type=config.default_location_type,
    )


def store_mrp_payload(
    config: PlanStorageConfig,
    *,
    mrp_data: Dict[str, Any],
    output_path: Path,
) -> bool:
    return write_mrp_result(
        version_id=config.version_id,
        mrp_data=mrp_data,
        output_path=output_path,
        storage_mode=config.storage_mode,
        default_location_key=config.default_location_key,
        default_location_type=config.default_location_type,
    )


def store_plan_final_payload(
    config: PlanStorageConfig,
    *,
    plan_final: Dict[str, Any],
    output_path: Path,
) -> bool:
    return write_plan_final_result(
        version_id=config.version_id,
        plan_final_data=plan_final,
        output_path=output_path,
        storage_mode=config.storage_mode,
        default_location_key=config.default_location_key,
        default_location_type=config.default_location_type,
    )


def store_anchor_adjust_payload(
    config: PlanStorageConfig,
    *,
    adjusted_data: Dict[str, Any],
    output_path: Path,
) -> bool:
    return write_anchor_adjust_result(
        version_id=config.version_id,
        adjusted_data=adjusted_data,
        output_path=output_path,
        storage_mode=config.storage_mode,
        default_location_key=config.default_location_key,
        default_location_type=config.default_location_type,
    )


def store_reconcile_log_payload(
    config: PlanStorageConfig,
    *,
    log_data: Dict[str, Any],
    output_path: Path,
    artifact_name: str,
) -> bool:
    return write_reconcile_log_result(
        version_id=config.version_id,
        log_data=log_data,
        output_path=output_path,
        storage_mode=config.storage_mode,
        artifact_name=artifact_name,
    )


def store_report_csv_payload(
    config: PlanStorageConfig,
    *,
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
    output_path: Path,
    artifact_name: str,
) -> bool:
    return write_report_csv_result(
        version_id=config.version_id,
        rows=rows,
        fieldnames=fieldnames,
        output_path=output_path,
        storage_mode=config.storage_mode,
        artifact_name=artifact_name,
    )


def _calendar_cli_args(
    *,
    calendar_path: Optional[Union[str, Path]] = None,
    input_dir: Optional[Union[str, Path]] = None,
    fallback_weeks: Optional[int] = None,
    supports_calendar: bool = True,
) -> List[str]:
    """planning_calendar.json を探索し、CLIへ渡す引数を構築する。

    supports_calendar が True の場合はカレンダーファイルが見つかれば --calendar を返す。
    見つからない場合、または supports_calendar=False の場合に fallback_weeks が指定されていれば
    --weeks を返し、週等分フォールバックを継続する。
    """

    path: Optional[Path] = None
    if calendar_path:
        candidate = Path(calendar_path)
        if candidate.exists():
            path = candidate
    if path is None and input_dir:
        candidate = Path(input_dir) / "planning_calendar.json"
        if candidate.exists():
            path = candidate

    if supports_calendar and path is not None:
        return ["--calendar", str(path)]

    if fallback_weeks is not None:
        weeks = max(1, int(fallback_weeks))
        return ["--weeks", str(weeks)]

    return []
