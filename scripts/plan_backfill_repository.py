#!/usr/bin/env python3
"""plan_artifacts から PlanRepository テーブルへデータをバックフィルするスクリプト。"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from app import db
from core.plan_repository import (
    PlanRepository,
    PlanRepositoryError,
    PlanKpiRow,
    PlanSeriesRow,
)
from core.plan_repository_builders import (
    build_plan_kpis_from_aggregate,
    build_plan_series_from_aggregate,
    build_plan_series_from_detail,
    build_plan_series_from_mrp,
    build_plan_series_from_plan_final,
    build_plan_series_from_weekly_summary,
)


logger = logging.getLogger("plan_backfill")


def setup_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclass
class BackfillCounts:
    processed: int = 0
    skipped: int = 0
    errors: int = 0


class BackfillError(RuntimeError):
    def __init__(self, version_id: str, message: str):
        super().__init__(message)
        self.version_id = version_id
        self.message = message


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill PlanRepository tables from plan_artifacts."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="処理するPlan versionの最大数。"
    )
    parser.add_argument(
        "--resume-from",
        dest="resume_from",
        default=None,
        help="指定version以降を処理する（version_id一致で再開）。",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="進捗を保存する状態ファイルパス（JSON）。",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="書き込みを行わずに処理内容を表示する。"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="PlanRepositoryに既存データがあっても再実行する。",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def load_state(path: Path | None) -> Tuple[set[str], Dict[str, str]]:
    if path is None or not path.exists():
        return set(), {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set(), {}
    completed = set(data.get("completed_versions") or [])
    failed = dict(data.get("failed_versions") or {})
    return completed, failed


def save_state(
    path: Path | None, completed: Iterable[str], failed: Dict[str, str]
) -> None:
    if path is None:
        return
    payload = {
        "completed_versions": sorted(set(completed)),
        "failed_versions": failed,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def iter_plan_versions(
    conn: sqlite3.Connection, resume_from: str | None
) -> Iterable[Dict[str, object]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM plan_versions ORDER BY created_at, version_id"
    ).fetchall()
    started = resume_from is None
    for row in rows:
        version_id = row["version_id"]
        if not started:
            if version_id == resume_from:
                started = True
            else:
                continue
        yield dict(row)


def has_plan_repository_data(conn: sqlite3.Connection, version_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM plan_series WHERE version_id=? LIMIT 1",
        (version_id,),
    )
    return cur.fetchone() is not None


def load_artifact(version_id: str, name: str) -> Dict[str, object] | None:
    try:
        return db.get_plan_artifact(version_id, name)
    except Exception:
        return None


def build_plan_payload(
    version: Dict[str, object],
) -> Tuple[List[PlanSeriesRow], List[PlanKpiRow]]:
    version_id = str(version["version_id"])

    aggregate = load_artifact(version_id, "aggregate.json")
    detail = load_artifact(version_id, "sku_week.json")
    mrp = load_artifact(version_id, "mrp.json")
    plan_final = load_artifact(version_id, "plan_final.json")
    source_meta = load_artifact(version_id, "source.json") or {}

    if not any([aggregate, detail, mrp, plan_final]):
        raise BackfillError(
            version_id, "バックフィル対象の成果物が見つかりませんでした"
        )

    series: List[PlanSeriesRow] = []
    kpis: List[PlanKpiRow] = []

    if aggregate:
        series.extend(
            build_plan_series_from_aggregate(
                version_id,
                aggregate,
                default_location_key="global",
                default_location_type="global",
            )
        )
        kpis.extend(build_plan_kpis_from_aggregate(version_id, aggregate))

    if detail:
        series.extend(
            build_plan_series_from_detail(
                version_id,
                detail,
                default_location_key="global",
                default_location_type="global",
            )
        )

    if mrp:
        series.extend(
            build_plan_series_from_mrp(
                version_id,
                mrp,
                default_location_key="global",
                default_location_type="global",
            )
        )

    if plan_final:
        series.extend(
            build_plan_series_from_plan_final(
                version_id,
                plan_final,
                default_location_key="global",
                default_location_type="global",
            )
        )
        series.extend(
            build_plan_series_from_weekly_summary(
                version_id,
                plan_final,
                default_location_key="global",
                default_location_type="global",
            )
        )

    if not series and not kpis:
        raise BackfillError(version_id, "成果物から生成されたデータが空でした")

    config_version_id = version.get("config_version_id")
    source_run_id = None
    if isinstance(source_meta, dict):
        source_run_id = source_meta.get("source_run_id") or source_meta.get("run_id")

    for row in series:
        if config_version_id is not None:
            row["config_version_id"] = config_version_id
        if source_run_id and not row.get("source_run_id"):
            row["source_run_id"] = source_run_id

    for row in kpis:
        if source_run_id and not row.get("source_run_id"):
            row["source_run_id"] = source_run_id

    return series, kpis


def _ensure_backfill_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_backfill_runs (
            run_id TEXT PRIMARY KEY,
            started_at INTEGER NOT NULL,
            finished_at INTEGER,
            status TEXT NOT NULL,
            processed INTEGER NOT NULL,
            skipped INTEGER NOT NULL,
            errors INTEGER NOT NULL,
            dry_run INTEGER NOT NULL,
            duration_ms INTEGER,
            limit_count INTEGER,
            resume_from TEXT,
            state_file TEXT,
            message TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plan_backfill_runs_started
        ON plan_backfill_runs(started_at DESC)
        """
    )


def _insert_backfill_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    started_at: int,
    dry_run: bool,
    limit_count: int | None,
    resume_from: str | None,
    state_file: Path | None,
) -> None:
    _ensure_backfill_table(conn)
    conn.execute(
        """
        INSERT INTO plan_backfill_runs (
            run_id, started_at, status, processed, skipped, errors,
            dry_run, limit_count, resume_from, state_file
        ) VALUES (?, ?, ?, 0, 0, 0, ?, ?, ?, ?)
        """,
        (
            run_id,
            started_at,
            "running",
            1 if dry_run else 0,
            limit_count,
            resume_from,
            str(state_file) if state_file else None,
        ),
    )


def _update_backfill_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    finished_at: int,
    status: str,
    counts: BackfillCounts,
    started_at: int,
    message: str | None = None,
) -> None:
    duration_ms = max(0, finished_at - started_at)
    conn.execute(
        """
        UPDATE plan_backfill_runs
        SET finished_at=?, status=?, processed=?, skipped=?, errors=?, duration_ms=?, message=?
        WHERE run_id=?
        """,
        (
            finished_at,
            status,
            counts.processed,
            counts.skipped,
            counts.errors,
            duration_ms,
            message,
            run_id,
        ),
    )


def run_backfill(args: argparse.Namespace) -> tuple[BackfillCounts, str]:
    setup_logging()
    db.init_db()
    repo = PlanRepository(db._conn)
    conn = db._conn()
    counts = BackfillCounts()
    completed_state, failed_state = load_state(args.state_file)
    run_id = uuid.uuid4().hex
    started_at = int(time.time() * 1000)
    run_status = "success"
    run_message: str | None = None

    try:
        _insert_backfill_run(
            conn,
            run_id=run_id,
            started_at=started_at,
            dry_run=args.dry_run,
            limit_count=args.limit,
            resume_from=args.resume_from,
            state_file=args.state_file,
        )
        conn.commit()
        logger.info(
            "backfill_started",
            extra={
                "event": "backfill_started",
                "run_id": run_id,
                "dry_run": args.dry_run,
                "limit": args.limit,
                "resume_from": args.resume_from,
                "state_file": str(args.state_file) if args.state_file else None,
            },
        )

        processed_versions = 0
        for version in iter_plan_versions(conn, args.resume_from):
            version_id = str(version["version_id"])

            if args.limit is not None and processed_versions >= args.limit:
                break
            processed_versions += 1

            if not args.force and version_id in completed_state:
                logger.info(
                    "backfill_skip_state",
                    extra={"event": "backfill_skip_state", "version_id": version_id},
                )
                print(f"[skip] {version_id}: state fileで既に完了扱い")
                counts.skipped += 1
                continue

            if not args.force and has_plan_repository_data(conn, version_id):
                logger.info(
                    "backfill_skip_existing",
                    extra={"event": "backfill_skip_existing", "version_id": version_id},
                )
                print(f"[skip] {version_id}: PlanRepositoryに既存データあり")
                counts.skipped += 1
                completed_state.add(version_id)
                failed_state.pop(version_id, None)
                continue

            try:
                series, kpis = build_plan_payload(version)
            except BackfillError as exc:
                logger.warning(
                    "backfill_artifact_missing",
                    extra={
                        "event": "backfill_artifact_missing",
                        "version_id": version_id,
                        "message": exc.message,
                    },
                )
                print(f"[warn] {version_id}: {exc.message}")
                counts.errors += 1
                if not args.dry_run:
                    failed_state[version_id] = exc.message
                continue

            if args.dry_run:
                logger.info(
                    "backfill_dry_run",
                    extra={
                        "event": "backfill_dry_run",
                        "version_id": version_id,
                        "series_rows": len(series),
                        "kpi_rows": len(kpis),
                    },
                )
                print(
                    f"[dry-run] {version_id}: series={len(series)} rows, kpis={len(kpis)} rows"
                )
                counts.skipped += 1
                continue

            try:
                repo.write_plan(
                    version_id,
                    series=series,
                    overrides=None,
                    override_events=None,
                    kpis=kpis,
                    job=None,
                    storage_mode="backfill",
                )
            except PlanRepositoryError as exc:
                message = f"PlanRepository書き込みに失敗しました: {exc}"
                logger.error(
                    "backfill_write_failed",
                    extra={
                        "event": "backfill_write_failed",
                        "version_id": version_id,
                        "message": message,
                    },
                )
                print(f"[error] {version_id}: {message}")
                counts.errors += 1
                failed_state[version_id] = message
                continue

            logger.info(
                "backfill_success",
                extra={
                    "event": "backfill_success",
                    "version_id": version_id,
                    "series_rows": len(series),
                    "kpi_rows": len(kpis),
                },
            )
            print(
                f"[ok] {version_id}: series={len(series)} rows, kpis={len(kpis)} rows"
            )
            counts.processed += 1
            completed_state.add(version_id)
            failed_state.pop(version_id, None)

    except Exception as exc:  # pragma: no cover - 想定外例外
        counts.errors += 1
        run_status = "failed"
        run_message = str(exc)
        logger.exception(
            "backfill_run_exception",
            extra={"event": "backfill_run_exception", "run_id": run_id},
        )
    finally:
        conn.close()
        finished_at = int(time.time() * 1000)
        if run_status == "success" and counts.errors > 0:
            run_status = "partial" if counts.processed > 0 else "failed"
        update_conn = db._conn()
        try:
            _update_backfill_run(
                update_conn,
                run_id=run_id,
                finished_at=finished_at,
                status=run_status,
                counts=counts,
                started_at=started_at,
                message=run_message,
            )
            update_conn.commit()
        finally:
            update_conn.close()

    if args.state_file and not args.dry_run and run_status != "failed":
        save_state(args.state_file, completed_state, failed_state)

    logger.log(
        logging.INFO if run_status == "success" else logging.WARNING,
        "backfill_completed",
        extra={
            "event": "backfill_completed",
            "run_id": run_id,
            "status": run_status,
            "processed": counts.processed,
            "skipped": counts.skipped,
            "errors": counts.errors,
        },
    )

    print(
        f"完了: processed={counts.processed}, skipped={counts.skipped}, errors={counts.errors}"
    )

    return counts, run_status


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    counts, status = run_backfill(args)
    if status != "success" or counts.errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
