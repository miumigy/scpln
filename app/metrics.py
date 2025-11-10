from __future__ import annotations

import os
from fastapi.responses import Response
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CONTENT_TYPE_LATEST,
    REGISTRY,
    generate_latest,
    start_http_server,
)

# ---------------------------------------------------------------------------
# Simulation / run APIs
# ---------------------------------------------------------------------------

RUNS_TOTAL = Counter(
    "scpln_runs_total",
    "Total number of simulations executed via /simulation",
)

RUNS_QUEUED = Counter(
    "runs_queued_total",
    "Number of runs enqueued for asynchronous execution",
)

SIM_DURATION = Histogram(
    "scpln_sim_duration_ms",
    "Simulation duration in milliseconds",
    buckets=(50, 100, 250, 500, 1000, 2000, 5000, 10000, 30000, float("inf")),
)

# ---------------------------------------------------------------------------
# Run listing / comparison APIs
# ---------------------------------------------------------------------------

RUNS_LIST_REQUESTS = Counter(
    "scpln_runs_list_requests_total",
    "Number of /runs listing requests",
    labelnames=("detail", "backend"),
)

RUNS_LIST_RETURNED = Histogram(
    "scpln_runs_list_returned",
    "Number of runs returned per listing request",
    buckets=(1, 5, 10, 20, 50, 100, 200, 500, 1000, float("inf")),
)

COMPARE_REQUESTS = Counter(
    "scpln_run_compare_requests_total",
    "Run compare API invocations",
    labelnames=("threshold", "keys", "runs", "base_set"),
)

COMPARE_DURATION = Histogram(
    "scpln_run_compare_duration_seconds",
    "Run compare API processing time",
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, float("inf")),
)

PLANS_CREATED_TOTAL = Counter(
    "plans_created_total",
    "Number of plans created",
)

PLANS_RECONCILED_TOTAL = Counter(
    "plans_reconciled_total",
    "Number of plan reconcile operations executed",
)

PLANS_VIEWED_TOTAL = Counter(
    "plans_viewed_total",
    "Number of plan detail page views",
)

PLAN_SCHEDULE_EXPORT_TOTAL = Counter(
    "plan_schedule_export_total",
    "Number of plan schedule CSV exports",
)

PLAN_COMPARE_EXPORT_TOTAL = Counter(
    "plan_compare_export_total",
    "Number of plan compare exports",
    labelnames=("mode",),
)

PLAN_CARRYOVER_EXPORT_TOTAL = Counter(
    "plan_carryover_export_total",
    "Number of plan carryover CSV exports",
)

PLAN_ARTIFACT_WRITE_ERROR_TOTAL = Counter(
    "plan_artifact_write_error_total",
    "Plan artifact persistence failures",
    labelnames=("artifact",),
)

# ---------------------------------------------------------------------------
# Plan repository metrics
# ---------------------------------------------------------------------------

PLAN_DB_WRITE_TOTAL = Counter(
    "plan_db_write_total",
    "Successful PlanRepository writes",
    labelnames=("storage_mode",),
)

PLAN_DB_WRITE_ERROR_TOTAL = Counter(
    "plan_db_write_error_total",
    "PlanRepository write failures",
    labelnames=("storage_mode", "error_type"),
)

PLAN_DB_WRITE_LATENCY = Histogram(
    "plan_db_write_latency_seconds",
    "PlanRepository write latency",
    labelnames=("storage_mode",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, float("inf")),
)

PLAN_SERIES_ROWS_TOTAL = Gauge(
    "plan_series_rows_total",
    "Number of plan_series rows written in the latest transaction",
)

PLAN_DB_LAST_SUCCESS_TIMESTAMP = Gauge(
    "plan_db_last_success_timestamp",
    "UNIX timestamp of the latest successful PlanRepository write",
)

PLAN_DB_CAPACITY_TRIM_TOTAL = Counter(
    "plan_db_capacity_trim_total",
    "PlanRepository capacity guard trims",
    labelnames=("reason",),
)

PLAN_DB_LAST_TRIM_TIMESTAMP = Gauge(
    "plan_db_last_trim_timestamp",
    "UNIX timestamp of the latest PlanRepository capacity trim",
)

# ---------------------------------------------------------------------------
# InputSet / legacy mode metrics
# ---------------------------------------------------------------------------

LEGACY_MODE_RUNS_TOTAL = Counter(
    "run_without_input_set_total",
    "Runs executed without an InputSet label (legacy mode)",
    labelnames=("entrypoint",),
)

# Backwards compatible alias for docs/code referencing the old name
RUN_WITHOUT_INPUT_SET_TOTAL = LEGACY_MODE_RUNS_TOTAL

INPUT_SET_DIFF_JOBS_TOTAL = Counter(
    "input_set_diff_jobs_total",
    "Background diff job executions",
    labelnames=("result",),
)

INPUT_SET_DIFF_CACHE_HITS_TOTAL = Counter(
    "input_set_diff_cache_hits_total",
    "Input set diff cache hits",
)

INPUT_SET_DIFF_CACHE_STALE_TOTAL = Counter(
    "input_set_diff_cache_stale_total",
    "Input set diff cache misses due to TTL expiry or errors",
)


# ---------------------------------------------------------------------------
# Metrics endpoint helpers
# ---------------------------------------------------------------------------


def metrics_snapshot() -> Response:
    """Return Prometheus exposition text for FastAPI /metrics endpoint."""
    payload = generate_latest(REGISTRY)
    return Response(payload, media_type=CONTENT_TYPE_LATEST)


def start_metrics_server(port: int | None = None) -> None:
    """Optional standalone metrics server for worker processes."""
    target_port = port or int(os.getenv("METRICS_PORT", "9000"))
    start_http_server(target_port)
