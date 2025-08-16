import io
import csv
from fastapi import HTTPException, Response
from app.api import app
from app.run_registry import REGISTRY

FIELDS = [
    "run_id",
    "day",
    "node",
    "item",
    "event",
    "qty",
    "unit_cost",
    "amount",
    "account",
]


@app.get("/runs/{run_id}/trace.csv")
def get_trace_csv(run_id: str):
    rec = REGISTRY.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    trace = rec.get("cost_trace") or []
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    for e in trace:
        row = {"run_id": run_id}
        row.update({k: e.get(k) for k in FIELDS if k != "run_id"})
        w.writerow(row)
    return Response(content=buf.getvalue(), media_type="text/csv")

