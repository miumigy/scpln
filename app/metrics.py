"""Prometheusメトリクス定義集。FastAPIアプリ全体で共有される。"""

from __future__ import annotations

import os
import time

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request

from app.db import _db_path


# --- シミュレーション実行メトリクス ---
RUNS_TOTAL = Counter("runs_total", "Total number of simulation runs")
SIM_DURATION = Histogram(
    "simulation_duration_ms",
    "Simulation duration in milliseconds",
    buckets=(50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000, float("inf")),
)
RUNS_LIST_REQUESTS = Counter(
    "runs_list_requests_total",
    "Total runs list API calls",
    labelnames=("detail", "backend"),
)
RUNS_LIST_RETURNED = Histogram(
    "runs_list_returned",
    "Number of runs returned by list API",
    buckets=(1, 5, 10, 20, 50, 100, 200, 500, float("inf")),
)


# --- HTTP共通メトリクス ---
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=("method", "path", "status"),
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=("method", "path", "status"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, float("inf")),
)


# --- Planning Hub固有メトリクス ---
PLANS_CREATED = Counter("plans_created_total", "Number of plans created")
PLANS_RECONCILED = Counter(
    "plans_reconciled_total",
    "Number of plan reconciliations executed",
)
PLANS_VIEWED = Counter("plans_viewed_total", "Number of plan detail views")
RUNS_QUEUED = Counter("runs_queued_total", "Number of background runs queued")
PLAN_EXPORT_SCHEDULE = Counter(
    "plan_schedule_export_total",
    "Exports of schedule.csv",
)
PLAN_EXPORT_COMPARE = Counter(
    "plan_compare_export_total",
    "Exports of compare.csv",
    labelnames=("mode",),
)
PLAN_EXPORT_CARRYOVER = Counter(
    "plan_carryover_export_total",
    "Exports of carryover.csv",
)

COMPARE_REQUESTS = Counter(
    "compare_requests_total",
    "Total compare API requests",
    labelnames=("threshold", "keys", "runs", "base_set"),
)

COMPARE_DURATION = Histogram(
    "compare_duration_seconds",
    "Compare API processing duration in seconds",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, float("inf")),
)


# --- PlanRepository関連メトリクス ---
PLAN_DB_WRITE_TOTAL = Counter(
    "plan_db_write_total",
    "Total successful writes to PlanRepository",
    labelnames=("storage_mode",),
)
PLAN_DB_WRITE_ERROR_TOTAL = Counter(
    "plan_db_write_error_total",
    "Total errors during writes to PlanRepository",
    labelnames=("storage_mode", "error_type"),
)
PLAN_DB_WRITE_LATENCY = Histogram(
    "plan_db_write_latency_seconds",
    "PlanRepository write_plan processing time",
    labelnames=("storage_mode",),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, float("inf")),
)
PLAN_SERIES_ROWS_TOTAL = Gauge(
    "plan_series_rows_written",
    "Number of rows written to plan_series table in the last successful write",
)
PLAN_DB_SIZE_BYTES = Gauge(
    "plan_db_size_bytes",
    "Size of the SQLite database file in bytes",
)
PLAN_DB_LAST_SUCCESS_TIMESTAMP = Gauge(
    "plan_db_last_success_timestamp_seconds",
    "Timestamp of the last successful PlanRepository write",
)
PLAN_DB_CAPACITY_TRIM_TOTAL = Counter(
    "plan_db_capacity_trim_total",
    "Number of plan versions trimmed by capacity guard",
    labelnames=("reason",),
)
PLAN_DB_LAST_TRIM_TIMESTAMP = Gauge(
    "plan_db_last_trim_timestamp_seconds",
    "Timestamp of the most recent PlanRepository capacity trim",
)


def observe_http(request: Request, status: int, started_at: float) -> None:
    """HTTPリクエストの基本メトリクスを計測する。失敗時は黙殺。"""

    try:
        path = request.url.path
        method = request.method
        elapsed = time.monotonic() - started_at
        HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
        HTTP_DURATION.labels(method=method, path=path, status=str(status)).observe(
            elapsed
        )
    except Exception:
        pass


def metrics_snapshot() -> Response:
    """/metricsエンドポイント向けの最新メトリクスを返す。"""

    try:
        db_path = _db_path()
        if os.path.exists(db_path):
            PLAN_DB_SIZE_BYTES.set(os.path.getsize(db_path))
    except Exception:
        # DBサイズ取得に失敗しても露出しない
        pass

    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
