from fastapi import Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from app.api import app

RUNS_TOTAL = Counter("runs_total", "Total number of simulation runs")
SIM_DURATION = Histogram(
    "simulation_duration_ms",
    "Simulation duration in milliseconds",
    buckets=(50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000, float("inf")),
)


@app.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

