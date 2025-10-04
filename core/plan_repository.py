"""Planデータ永続化レイヤ。

Alembicで追加した各テーブルへ書き込み・読出しを行い、Plan周辺の
トランザクションを一元化する。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from collections.abc import Callable, Iterable, Sequence
from typing import Any, NotRequired, TypedDict




def _now_ms() -> int:
    return int(time.time() * 1000)


class PlanRepositoryError(RuntimeError):
    """Plan永続化時のラップド例外。"""


class PlanSeriesRow(TypedDict):
    version_id: str
    level: str
    time_bucket_type: str
    time_bucket_key: str
    item_key: str
    location_key: str
    item_name: NotRequired[str | None]
    location_type: NotRequired[str | None]
    region_key: NotRequired[str | None]
    network_key: NotRequired[str | None]
    scenario_id: NotRequired[int | None]
    config_version_id: NotRequired[int | None]
    source: NotRequired[str | None]
    policy: NotRequired[str | None]
    cutover_flag: NotRequired[bool]
    boundary_zone: NotRequired[str | None]
    window_index: NotRequired[int | None]
    lock_flag: NotRequired[bool]
    locked_by: NotRequired[str | None]
    quality_flag: NotRequired[str | None]
    source_run_id: NotRequired[str | None]
    demand: NotRequired[float | None]
    supply: NotRequired[float | None]
    backlog: NotRequired[float | None]
    inventory_open: NotRequired[float | None]
    inventory_close: NotRequired[float | None]
    prod_qty: NotRequired[float | None]
    ship_qty: NotRequired[float | None]
    capacity_used: NotRequired[float | None]
    cost_total: NotRequired[float | None]
    service_level: NotRequired[float | None]
    spill_in: NotRequired[float | None]
    spill_out: NotRequired[float | None]
    adjustment: NotRequired[float | None]
    carryover_in: NotRequired[float | None]
    carryover_out: NotRequired[float | None]
    extra_json: NotRequired[str | None]
    created_at: NotRequired[int]
    updated_at: NotRequired[int]


class PlanOverrideRow(TypedDict):
    version_id: str
    level: str
    key_hash: str
    payload_json: NotRequired[str | None]
    lock_flag: NotRequired[bool]
    locked_by: NotRequired[str | None]
    weight: NotRequired[float | None]
    author: NotRequired[str | None]
    source: NotRequired[str | None]
    created_at: NotRequired[int]
    updated_at: NotRequired[int]


class PlanOverrideEventRow(TypedDict):
    override_id: NotRequired[int | None]
    version_id: str
    level: str
    key_hash: str
    event_type: str
    event_ts: NotRequired[int]
    payload_json: NotRequired[str | None]
    actor: NotRequired[str | None]
    notes: NotRequired[str | None]


class PlanKpiRow(TypedDict):
    version_id: str
    metric: str
    bucket_type: NotRequired[str | None]
    bucket_key: NotRequired[str | None]
    value: NotRequired[float | None]
    unit: NotRequired[str | None]
    source: NotRequired[str | None]
    source_run_id: NotRequired[str | None]
    created_at: NotRequired[int]
    updated_at: NotRequired[int]


class PlanJobRow(TypedDict):
    job_id: str
    version_id: str
    status: str
    submitted_at: NotRequired[int]
    started_at: NotRequired[int | None]
    finished_at: NotRequired[int | None]
    duration_ms: NotRequired[int | None]
    retry_count: NotRequired[int]
    config_version_id: NotRequired[int | None]
    scenario_id: NotRequired[int | None]
    run_id: NotRequired[str | None]
    trigger: NotRequired[str | None]
    error: NotRequired[str | None]
    payload_json: NotRequired[str | None]


_PLAN_SERIES_COLUMNS: Sequence[str] = (
    "version_id",
    "level",
    "time_bucket_type",
    "time_bucket_key",
    "item_key",
    "item_name",
    "location_key",
    "location_type",
    "region_key",
    "network_key",
    "scenario_id",
    "config_version_id",
    "source",
    "policy",
    "cutover_flag",
    "boundary_zone",
    "window_index",
    "lock_flag",
    "locked_by",
    "quality_flag",
    "source_run_id",
    "demand",
    "supply",
    "backlog",
    "inventory_open",
    "inventory_close",
    "prod_qty",
    "ship_qty",
    "capacity_used",
    "cost_total",
    "service_level",
    "spill_in",
    "spill_out",
    "adjustment",
    "carryover_in",
    "carryover_out",
    "extra_json",
    "created_at",
    "updated_at",
)


_PLAN_OVERRIDE_COLUMNS: Sequence[str] = (
    "version_id",
    "level",
    "key_hash",
    "payload_json",
    "lock_flag",
    "locked_by",
    "weight",
    "author",
    "source",
    "created_at",
    "updated_at",
)


_PLAN_OVERRIDE_EVENT_COLUMNS: Sequence[str] = (
    "override_id",
    "version_id",
    "level",
    "key_hash",
    "event_type",
    "event_ts",
    "payload_json",
    "actor",
    "notes",
)


_PLAN_KPI_COLUMNS: Sequence[str] = (
    "version_id",
    "metric",
    "bucket_type",
    "bucket_key",
    "value",
    "unit",
    "source",
    "source_run_id",
    "created_at",
    "updated_at",
)


_PLAN_JOB_COLUMNS: Sequence[str] = (
    "job_id",
    "version_id",
    "config_version_id",
    "scenario_id",
    "status",
    "run_id",
    "trigger",
    "submitted_at",
    "started_at",
    "finished_at",
    "duration_ms",
    "retry_count",
    "error",
    "payload_json",
)


class _NullMetric:
    def labels(self, **_kwargs):  # pragma: no cover - noop
        return self

    def observe(self, *_args, **_kwargs):  # pragma: no cover - noop
        return None

    def set(self, *_args, **_kwargs):  # pragma: no cover - noop
        return None

    def inc(self, *_args, **_kwargs):  # pragma: no cover - noop
        return None

    def set_to_current_time(self):  # pragma: no cover - noop
        return None


class PlanRepository:
    """Plan DBテーブル群へのアクセサ。"""

    def __init__(
        self,
        conn_factory: Callable[[], sqlite3.Connection],
        plan_db_write_latency: Any | None = None,
        plan_series_rows_total: Any | None = None,
        plan_db_last_success_timestamp: Any | None = None,
        plan_db_guard_trim_total: Any | None = None,
        plan_db_last_trim_timestamp: Any | None = None,
    ):
        self._conn_factory = conn_factory
        self._plan_db_write_latency = plan_db_write_latency or _NullMetric()
        self._plan_series_rows_total = plan_series_rows_total or _NullMetric()
        self._plan_db_last_success_timestamp = (
            plan_db_last_success_timestamp or _NullMetric()
        )
        self._plan_db_guard_trim_total = plan_db_guard_trim_total or _NullMetric()
        self._capacity_env_key = "PLANS_DB_MAX_ROWS"
        self._trim_alert_threshold_key = "PLANS_DB_GUARD_ALERT_THRESHOLD"
        self._plan_db_last_trim_timestamp = (
            plan_db_last_trim_timestamp or _NullMetric()
        )

    # --- public API -------------------------------------------------
    def write_plan(
        self,
        version_id: str,
        *,
        series: Iterable[PlanSeriesRow],
        overrides: Iterable[PlanOverrideRow] | None = None,
        override_events: Iterable[PlanOverrideEventRow] | None = None,
        kpis: Iterable[PlanKpiRow] | None = None,
        job: PlanJobRow | None = None,
        storage_mode: str = "unknown",
    ) -> None:
        """Plan一式を書き込み。既存versionの行は置き換える。"""

        t0 = time.monotonic()
        success = False
        try:
            now = _now_ms()
            series_rows = [
                self._normalize_series_row(version_id, row, now) for row in series
            ]
            override_rows = [
                self._normalize_override_row(version_id, row, now)
                for row in (overrides or [])
            ]
            event_rows = [
                self._normalize_override_event_row(version_id, row, now)
                for row in (override_events or [])
            ]
            kpi_rows = [
                self._normalize_kpi_row(version_id, row, now) for row in (kpis or [])
            ]
            job_row = (
                self._normalize_job_row(version_id, job, now) if job is not None else None
            )

            conn = self._conn_factory()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._delete_plan(conn, version_id)
                if series_rows:
                    conn.executemany(
                        self._build_insert_sql("plan_series", _PLAN_SERIES_COLUMNS),
                        series_rows,
                    )
                if override_rows:
                    conn.executemany(
                        self._build_insert_sql("plan_overrides", _PLAN_OVERRIDE_COLUMNS),
                        override_rows,
                    )
                if event_rows:
                    conn.executemany(
                        self._build_insert_sql(
                            "plan_override_events", _PLAN_OVERRIDE_EVENT_COLUMNS
                        ),
                        event_rows,
                    )
                if kpi_rows:
                    conn.executemany(
                        self._build_insert_sql("plan_kpis", _PLAN_KPI_COLUMNS),
                        kpi_rows,
                    )
                if job_row:
                    conn.execute(
                        self._build_insert_sql(
                            "plan_jobs", _PLAN_JOB_COLUMNS, replace=True
                        ),
                        job_row,
                    )
                conn.commit()

                # --- Metrics on success ---
                self._plan_series_rows_total.set(len(series_rows))
                self._plan_db_last_success_timestamp.set_to_current_time()
                success = True

            except sqlite3.Error as exc:  # pragma: no cover - DB障害
                conn.rollback()
                raise PlanRepositoryError(
                    f"planデータ書込みに失敗しました: {exc}"
                ) from exc
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        finally:
            duration = time.monotonic() - t0
            self._plan_db_write_latency.labels(storage_mode=storage_mode).observe(duration)
        if success:
            try:
                self._enforce_capacity_guard()
            except Exception:  # pragma: no cover - ガード失敗はログのみに留める
                logging.exception("plan_repository_capacity_guard_failed")

    def fetch_plan_series(
        self,
        version_id: str,
        level: str,
        *,
        bucket_type: str | None = None,
        bucket_key: str | None = None,
    ) -> list[dict]:
        sql = [
            "SELECT * FROM plan_series WHERE version_id=? AND level=?",
        ]
        params: list[object] = [version_id, level]
        if bucket_type is not None:
            sql.append("AND time_bucket_type=?")
            params.append(bucket_type)
        if bucket_key is not None:
            sql.append("AND time_bucket_key=?")
            params.append(bucket_key)
        sql.append("ORDER BY time_bucket_type, time_bucket_key, item_key, location_key")
        return self._fetch_rows(" ".join(sql), tuple(params))

    def fetch_plan_overrides(self, version_id: str, level: str | None = None) -> list[dict]:
        sql = ["SELECT * FROM plan_overrides WHERE version_id=?"]
        params: list[object] = [version_id]
        if level is not None:
            sql.append("AND level=?")
            params.append(level)
        sql.append("ORDER BY updated_at DESC")
        return self._fetch_rows(" ".join(sql), tuple(params))

    def fetch_plan_override_events(self, version_id: str) -> list[dict]:
        sql = (
            "SELECT * FROM plan_override_events WHERE version_id=? "
            "ORDER BY event_ts DESC, id DESC"
        )
        return self._fetch_rows(sql, (version_id,))

    def fetch_plan_kpis(
        self, version_id: str, metric: str | None = None
    ) -> list[dict]:
        sql = ["SELECT * FROM plan_kpis WHERE version_id=?"]
        params: list[object] = [version_id]
        if metric is not None:
            sql.append("AND metric=?")
            params.append(metric)
        sql.append("ORDER BY bucket_type, bucket_key")
        return self._fetch_rows(" ".join(sql), tuple(params))

    def fetch_plan_jobs(
        self,
        *,
        version_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        sql = ["SELECT * FROM plan_jobs WHERE 1=1"]
        params: list[object] = []
        if version_id is not None:
            sql.append("AND version_id=?")
            params.append(version_id)
        if status is not None:
            sql.append("AND status=?")
            params.append(status)
        sql.append("ORDER BY submitted_at DESC")
        return self._fetch_rows(" ".join(sql), tuple(params))

    def delete_plan(self, version_id: str) -> None:
        conn = self._conn_factory()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._delete_plan(conn, version_id)
            conn.commit()
        except sqlite3.Error as exc:  # pragma: no cover - DB障害
            conn.rollback()
            raise PlanRepositoryError(
                f"planデータ削除に失敗しました: {exc}"
            ) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def trim_kpis_by_age(self, months: int) -> int:
        """
        Deletes KPI records older than a specified number of months.
        Returns the number of deleted rows.
        """
        if months <= 0:
            return 0

        # created_at is in milliseconds, so we calculate the cutoff timestamp in ms.
        cutoff_dt = datetime.now() - timedelta(days=months * 30)  # Approximate
        cutoff_timestamp_ms = int(cutoff_dt.timestamp() * 1000)

        conn = self._conn_factory()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "DELETE FROM plan_kpis WHERE created_at < ?", (cutoff_timestamp_ms,)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            logging.info(
                "plan_repository_kpis_trimmed",
                extra={
                    "event": "plan_repository_kpis_trimmed",
                    "deleted_rows": deleted_count,
                    "retention_months": months,
                },
            )
            return deleted_count
        except sqlite3.Error as exc:
            conn.rollback()
            raise PlanRepositoryError(f"KPIデータのトリムに失敗しました: {exc}") from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def replace_plan_series_level(
        self, version_id: str, level: str, rows: Iterable[PlanSeriesRow]
    ) -> None:
        now = _now_ms()
        normalized_rows = [
            self._normalize_series_row(
                version_id,
                row if row.get("level") else {**row, "level": level},
                now,
            )
            for row in rows
        ]

        conn = self._conn_factory()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM plan_series WHERE version_id=? AND level=?",
                (version_id, level),
            )
            if normalized_rows:
                conn.executemany(
                    self._build_insert_sql("plan_series", _PLAN_SERIES_COLUMNS),
                    normalized_rows,
                )
            conn.commit()
        except sqlite3.Error as exc:  # pragma: no cover - DB障害
            conn.rollback()
            raise PlanRepositoryError(
                f"planシリーズ({level})更新に失敗しました: {exc}"
            ) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- internal ---------------------------------------------------
    def _delete_plan(self, conn: sqlite3.Connection, version_id: str) -> None:
        conn.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_override_events WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))

    def _enforce_capacity_guard(self) -> None:
        max_rows = self._read_capacity_limit()
        if max_rows <= 0:
            return
        self._cleanup_by_capacity(max_rows)

    def _read_capacity_limit(self) -> int:
        try:
            value = os.getenv(self._capacity_env_key, "0") or "0"
            return max(0, int(value))
        except Exception:
            return 0

    def _cleanup_by_capacity(self, max_rows: int) -> None:
        if max_rows <= 0:
            return
        conn = self._conn_factory()
        trimmed = 0
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT COUNT(*) AS cnt FROM plan_versions").fetchone()
            total = int(row["cnt"] if row else 0)
            if total <= max_rows:
                conn.commit()
                return
            rows = conn.execute(
                """
                SELECT version_id FROM plan_versions
                ORDER BY created_at DESC, version_id DESC
                LIMIT -1 OFFSET ?
                """,
                (max_rows,),
            ).fetchall()
            version_ids = [r["version_id"] for r in rows]
            for vid in version_ids:
                self._delete_plan(conn, vid)
                conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (vid,))
                conn.execute("DELETE FROM plan_versions WHERE version_id=?", (vid,))
                trimmed += 1
            conn.commit()
        except sqlite3.Error:  # pragma: no cover - DB障害
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        if trimmed > 0:
            try:
                self._plan_db_guard_trim_total.labels(reason="max_rows").inc(trimmed)
            except Exception:  # pragma: no cover - label未対応
                try:
                    self._plan_db_guard_trim_total.inc(trimmed)
                except Exception:
                    pass
            try:
                self._plan_db_last_trim_timestamp.set(time.time())
            except Exception:
                pass
            logging.info(
                "plan_repository_capacity_trimmed",
                extra={
                    "event": "plan_repository_capacity_trimmed",
                    "deleted_versions": trimmed,
                    "max_rows": max_rows,
                },
            )
            alert_threshold = self._read_trim_alert_threshold()
            if alert_threshold > 0 and trimmed >= alert_threshold:
                logging.warning(
                    "plan_repository_capacity_trim_alert",
                    extra={
                        "event": "plan_repository_capacity_trim_alert",
                        "deleted_versions": trimmed,
                        "max_rows": max_rows,
                        "alert_threshold": alert_threshold,
                    },
                )

    def _normalize_series_row(
        self, version_id: str, row: PlanSeriesRow, now: int
    ) -> tuple:
        def _flt(value: float | None, default: float = 0.0) -> float:
            return float(value) if value is not None else default

        def _bool(value: bool | None) -> int:
            return 1 if value else 0

        level = row.get("level")
        bucket_type = row.get("time_bucket_type")
        bucket_key = row.get("time_bucket_key")
        item_key = row.get("item_key")
        location_key = row.get("location_key")
        if not level:
            raise PlanRepositoryError("PlanSeriesRow.level が未指定です")
        if not bucket_type:
            raise PlanRepositoryError("PlanSeriesRow.time_bucket_type が未指定です")
        if not bucket_key:
            raise PlanRepositoryError("PlanSeriesRow.time_bucket_key が未指定です")
        if not item_key:
            raise PlanRepositoryError("PlanSeriesRow.item_key が未指定です")
        if not location_key:
            raise PlanRepositoryError("PlanSeriesRow.location_key が未指定です")

        return (
            row.get("version_id", version_id),
            level,
            bucket_type,
            bucket_key,
            item_key,
            row.get("item_name"),
            location_key,
            row.get("location_type"),
            row.get("region_key"),
            row.get("network_key"),
            row.get("scenario_id"),
            row.get("config_version_id"),
            row.get("source"),
            row.get("policy"),
            _bool(row.get("cutover_flag")),
            row.get("boundary_zone"),
            row.get("window_index"),
            _bool(row.get("lock_flag")),
            row.get("locked_by"),
            row.get("quality_flag"),
            row.get("source_run_id"),
            _flt(row.get("demand")),
            _flt(row.get("supply")),
            _flt(row.get("backlog")),
            _flt(row.get("inventory_open")),
            _flt(row.get("inventory_close")),
            _flt(row.get("prod_qty")),
            _flt(row.get("ship_qty")),
            _flt(row.get("capacity_used")),
            _flt(row.get("cost_total")),
            row.get("service_level"),
            row.get("spill_in"),
            row.get("spill_out"),
            row.get("adjustment"),
            row.get("carryover_in"),
            row.get("carryover_out"),
            row.get("extra_json", "{}"),
            row.get("created_at", now),
            row.get("updated_at", now),
        )

    def _read_trim_alert_threshold(self) -> int:
        try:
            value = os.getenv(self._trim_alert_threshold_key, "0") or "0"
            return max(0, int(value))
        except Exception:
            return 0

    def _normalize_override_row(
        self, version_id: str, row: PlanOverrideRow, now: int
    ) -> tuple:
        def _bool(value: bool | None) -> int:
            return 1 if value else 0

        level = row.get("level")
        key_hash = row.get("key_hash")
        if not level:
            raise PlanRepositoryError("PlanOverrideRow.level が未指定です")
        if not key_hash:
            raise PlanRepositoryError("PlanOverrideRow.key_hash が未指定です")

        return (
            row.get("version_id", version_id),
            level,
            key_hash,
            row.get("payload_json", "{}"),
            _bool(row.get("lock_flag")),
            row.get("locked_by"),
            row.get("weight"),
            row.get("author"),
            row.get("source"),
            row.get("created_at", now),
            row.get("updated_at", now),
        )

    def _normalize_override_event_row(
        self, version_id: str, row: PlanOverrideEventRow, now: int
    ) -> tuple:
        level = row.get("level") or "aggregate"
        key_hash = row.get("key_hash")
        event_type = row.get("event_type") or "edit"
        if not key_hash:
            raise PlanRepositoryError("PlanOverrideEventRow.key_hash が未指定です")

        return (
            row.get("override_id"),
            row.get("version_id", version_id),
            level,
            key_hash,
            event_type,
            row.get("event_ts", now),
            row.get("payload_json", "{}"),
            row.get("actor"),
            row.get("notes"),
        )

    def _normalize_kpi_row(
        self, version_id: str, row: PlanKpiRow, now: int
    ) -> tuple:
        metric = row.get("metric")
        if not metric:
            raise PlanRepositoryError("PlanKpiRow.metric が未指定です")

        bucket_type = row.get("bucket_type") or "total"
        bucket_key = row.get("bucket_key") or "total"

        return (
            row.get("version_id", version_id),
            metric,
            bucket_type,
            bucket_key,
            float(row.get("value", 0.0) or 0.0),
            row.get("unit"),
            row.get("source"),
            row.get("source_run_id"),
            row.get("created_at", now),
            row.get("updated_at", now),
        )

    def _normalize_job_row(
        self, version_id: str, row: PlanJobRow, now: int
    ) -> tuple:
        try:
            job_id = row["job_id"]
        except KeyError as exc:  # pragma: no cover - データ不備
            raise PlanRepositoryError("PlanJobRow.job_id が未指定です") from exc
        status = row.get("status")
        if not status:
            raise PlanRepositoryError("PlanJobRow.status が未指定です")

        return (
            job_id,
            row.get("version_id", version_id),
            row.get("config_version_id"),
            row.get("scenario_id"),
            status,
            row.get("run_id"),
            row.get("trigger"),
            row.get("submitted_at", now),
            row.get("started_at"),
            row.get("finished_at"),
            row.get("duration_ms"),
            row.get("retry_count", 0),
            row.get("error"),
            row.get("payload_json"),
        )

    def _build_insert_sql(
        self, table: str, columns: Sequence[str], *, replace: bool = False
    ) -> str:
        placeholders = ",".join(["?"] * len(columns))
        col_csv = ",".join(columns)
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        return f"{verb} INTO {table}({col_csv}) VALUES({placeholders})"

    def _fetch_rows(self, sql: str, params: tuple[object, ...]) -> list[dict]:
        conn = self._conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]
            for row in rows:
                self._postprocess_row(row)
            return rows
        finally:
            conn.close()

    def _postprocess_row(self, row: dict) -> None:
        for key in ("cutover_flag", "lock_flag"):
            if key in row and row[key] is not None:
                row[key] = bool(row[key])

    def fetch_series_stats(
        self, version_ids: Iterable[str]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        version_ids = list(dict.fromkeys(version_ids))
        if not version_ids:
            return {}

        placeholders = ",".join(["?"] * len(version_ids))
        sql = (
            "SELECT version_id, level, COUNT(*) AS row_count, "
            "SUM(demand) AS demand_sum, SUM(supply) AS supply_sum, "
            "SUM(backlog) AS backlog_sum, SUM(capacity_used) AS capacity_sum, "
            "MAX(updated_at) AS max_updated_at "
            "FROM plan_series WHERE version_id IN (" + placeholders + ") "
            "GROUP BY version_id, level"
        )
        conn = self._conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, version_ids).fetchall()
        finally:
            conn.close()

        stats: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            vid = str(row["version_id"])
            level = str(row["level"])
            stats.setdefault(vid, {})[level] = {
                "row_count": int(row["row_count"] or 0),
                "demand_sum": float(row["demand_sum"] or 0.0),
                "supply_sum": float(row["supply_sum"] or 0.0),
                "backlog_sum": float(row["backlog_sum"] or 0.0),
                "capacity_sum": (
                    float(row["capacity_sum"]) if row["capacity_sum"] is not None else None
                ),
                "max_updated_at": int(row["max_updated_at"] or 0),
            }
        return stats

    def fetch_plan_kpi_totals(
        self, version_ids: Iterable[str]
    ) -> dict[str, dict[str, float]]:
        version_ids = list(dict.fromkeys(version_ids))
        if not version_ids:
            return {}

        placeholders = ",".join(["?"] * len(version_ids))
        sql = (
            "SELECT version_id, metric, bucket_type, bucket_key, value "
            "FROM plan_kpis WHERE version_id IN (" + placeholders + ")"
        )
        conn = self._conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, version_ids).fetchall()
        finally:
            conn.close()

        kpi_map: dict[str, dict[str, float]] = {}
        for row in rows:
            if str(row["bucket_type"]).lower() != "total":
                continue
            vid = str(row["version_id"])
            metric = str(row["metric"])
            value = row["value"]
            try:
                value_f = float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                value_f = 0.0
            kpi_map.setdefault(vid, {})[metric] = value_f
        return kpi_map

    def fetch_last_jobs(self, version_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        version_ids = list(dict.fromkeys(version_ids))
        if not version_ids:
            return {}

        placeholders = ",".join(["?"] * len(version_ids))
        sql = (
            "SELECT pj.* FROM plan_jobs pj "
            "JOIN (SELECT version_id, MAX(submitted_at) AS max_submitted "
            "FROM plan_jobs WHERE version_id IN (" + placeholders + ") "
            "GROUP BY version_id) latest "
            "ON pj.version_id = latest.version_id AND pj.submitted_at = latest.max_submitted"
        )

        conn = self._conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, version_ids).fetchall()
        finally:
            conn.close()

        jobs: dict[str, dict[str, Any]] = {}
        for row in rows:
            jobs[str(row["version_id"])] = dict(row)
        return jobs

    def upsert_overrides(
        self,
        version_id: str,
        *,
        overrides: Iterable[PlanOverrideRow],
        events: Iterable[PlanOverrideEventRow],
    ) -> None:
        override_rows = list(overrides)
        event_rows = list(events)
        if not override_rows and not event_rows:
            return

        now = _now_ms()
        conn = self._conn_factory()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if override_rows:
                upsert_sql = (
                    "INSERT INTO plan_overrides("
                    "version_id, level, key_hash, payload_json, lock_flag, "
                    "locked_by, weight, author, source, created_at, updated_at"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(version_id, level, key_hash) DO UPDATE SET "
                    "payload_json=excluded.payload_json, "
                    "lock_flag=excluded.lock_flag, "
                    "locked_by=excluded.locked_by, "
                    "weight=excluded.weight, "
                    "author=excluded.author, "
                    "source=excluded.source, "
                    "updated_at=excluded.updated_at"
                )
                for row in override_rows:
                    normalized = self._normalize_override_row(version_id, row, now)
                    conn.execute(upsert_sql, normalized)
            override_id_map: dict[tuple[str, str], int] = {}
            if override_rows:
                cursor = conn.execute(
                    "SELECT id, level, key_hash FROM plan_overrides WHERE version_id=?",
                    (version_id,),
                )
                for rec in cursor.fetchall():
                    level = rec[1]
                    key_hash = rec[2]
                    if level is None or key_hash is None:
                        continue
                    override_id_map[(str(level), str(key_hash))] = rec[0]
            if event_rows:
                insert_sql = (
                    "INSERT INTO plan_override_events("
                    "override_id, version_id, level, key_hash, event_type, event_ts, "
                    "payload_json, actor, notes"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )
                for row in event_rows:
                    normalized_event = self._normalize_override_event_row(
                        version_id, row, now
                    )
                    event_dict = dict(zip(_PLAN_OVERRIDE_EVENT_COLUMNS, normalized_event))
                    level = str(event_dict.get("level") or "aggregate")
                    key_hash = str(event_dict.get("key_hash") or "")
                    override_id = event_dict.get("override_id")
                    if not override_id:
                        override_id = override_id_map.get((level, key_hash))
                    if not override_id:
                        continue
                    params = (
                        override_id,
                        event_dict.get("version_id"),
                        level,
                        key_hash,
                        event_dict.get("event_type"),
                        event_dict.get("event_ts"),
                        event_dict.get("payload_json"),
                        event_dict.get("actor"),
                        event_dict.get("notes"),
                    )
                    conn.execute(insert_sql, params)
            conn.commit()
        except sqlite3.Error as exc:  # pragma: no cover - DB障害
            conn.rollback()
            raise PlanRepositoryError(
                f"plan override書込みに失敗しました: {exc}"
            ) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
