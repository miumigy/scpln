from fastapi import Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import time
import os
from starlette.requests import Request
from app.db import _db_path

RUNS_TOTAL = Counter("runs_total", "Total number of simulation runs")
