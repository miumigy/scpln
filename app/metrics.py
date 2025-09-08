from fastapi import Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time
from starlette.requests import Request
from app.api import app

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

# Planning Hub specific KPIs
PLANS_CREATED = Counter("plans_created_total", "Number of plans created")
PLANS_RECONCILED = Counter(
    "plans_reconciled_total", "Number of plan reconciliations executed"
)
PLANS_VIEWED = Counter("plans_viewed_total", "Number of plan detail views")
RUNS_QUEUED = Counter("runs_queued_total", "Number of background runs queued")
PLAN_EXPORT_SCHEDULE = Counter("plan_schedule_export_total", "Exports of schedule.csv")
PLAN_EXPORT_COMPARE = Counter(
    "plan_compare_export_total", "Exports of compare.csv", labelnames=("mode",)
)
PLAN_EXPORT_CARRYOVER = Counter(
    "plan_carryover_export_total", "Exports of carryover.csv"
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


def observe_http(request: Request, status: int, started_at: float) -> None:
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


@app.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
