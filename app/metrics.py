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

def observe_http(request: Request, status: int, started_at: float) -> None:
    try:
        path = request.url.path
        method = request.method
        elapsed = time.monotonic() - started_at
        HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
        HTTP_DURATION.labels(method=method, path=path, status=str(status)).observe(elapsed)
    except Exception:
        pass


@app.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
