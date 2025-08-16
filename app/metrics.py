from app.api import app
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
