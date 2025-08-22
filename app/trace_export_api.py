import io
import csv
import json
from typing import Any, Dict, Iterable, List, Set
from fastapi import HTTPException, Response
from starlette.responses import StreamingResponse
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

    def _iter():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=FIELDS)
        w.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for e in trace:
            row = {"run_id": run_id}
            row.update({k: e.get(k) for k in FIELDS if k != "run_id"})
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    headers = {"Content-Disposition": f"attachment; filename=trace_{run_id}.csv"}
    return StreamingResponse(_iter(), media_type="text/csv; charset=utf-8", headers=headers)


def _flatten(d: Dict[str, Any], parent: str = "", sep: str = ".") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (d or {}).items():
        key = f"{parent}{sep}{k}" if parent else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, key, sep))
        elif isinstance(v, (list, tuple)):
            out[key] = json.dumps(v, ensure_ascii=False)
        else:
            out[key] = v
    return out


def _collect_fieldnames(rows: Iterable[Dict[str, Any]]) -> List[str]:
    fields: Set[str] = set()
    for r in rows:
        fields.update(r.keys())
    return ["run_id", *sorted([f for f in fields if f != "run_id"])]


@app.get("/runs/{run_id}/results.csv")
def get_results_csv(run_id: str):
    rec = REGISTRY.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    results = rec.get("results") or []
    # 1st pass: collect header
    field_set: Set[str] = set()
    for r in results:
        flat = (
            _flatten(r)
            if isinstance(r, dict)
            else {"data": json.dumps(r, ensure_ascii=False)}
        )
        field_set.update(flat.keys())
    fieldnames = ["run_id", *sorted([f for f in field_set if f != "run_id"])]

    def _iter():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames)
        w.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for r in results:
            flat = (
                _flatten(r)
                if isinstance(r, dict)
                else {"data": json.dumps(r, ensure_ascii=False)}
            )
            row = {"run_id": run_id, **flat}
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    headers = {"Content-Disposition": f"attachment; filename=results_{run_id}.csv"}
    return StreamingResponse(_iter(), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/runs/{run_id}/pl.csv")
def get_pl_csv(run_id: str):
    rec = REGISTRY.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    pl = rec.get("daily_profit_loss") or []
    # 1st pass: collect header
    field_set: Set[str] = set()
    for r in pl:
        flat = (
            _flatten(r)
            if isinstance(r, dict)
            else {"data": json.dumps(r, ensure_ascii=False)}
        )
        field_set.update(flat.keys())
    fieldnames = ["run_id", *sorted([f for f in field_set if f != "run_id"])]

    def _iter():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames)
        w.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for r in pl:
            flat = (
                _flatten(r)
                if isinstance(r, dict)
                else {"data": json.dumps(r, ensure_ascii=False)}
            )
            row = {"run_id": run_id, **flat}
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    headers = {"Content-Disposition": f"attachment; filename=pl_{run_id}.csv"}
    return StreamingResponse(_iter(), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/runs/{run_id}/summary.csv")
def get_summary_csv(run_id: str):
    rec = REGISTRY.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    summary = rec.get("summary") or {}
    flat = _flatten(summary)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["run_id", "metric", "value"])
    w.writeheader()
    for k in sorted(flat.keys()):
        w.writerow({"run_id": run_id, "metric": k, "value": flat[k]})
    headers = {"Content-Disposition": f"attachment; filename=summary_{run_id}.csv"}
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/runs/{run_id}/config.json")
def get_config_json(run_id: str):
    rec = REGISTRY.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    cfg = {
        "run_id": run_id,
        "config_id": rec.get("config_id"),
        "config_json": rec.get("config_json"),
    }
    return cfg


@app.get("/runs/{run_id}/config.csv")
def get_config_csv(run_id: str):
    rec = REGISTRY.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["run_id", "config_id", "config_json"])
    w.writeheader()
    w.writerow(
        {
            "run_id": run_id,
            "config_id": rec.get("config_id"),
            "config_json": json.dumps(rec.get("config_json"), ensure_ascii=False)
            if rec.get("config_json") is not None
            else None,
        }
    )
    headers = {"Content-Disposition": f"attachment; filename=config_{run_id}.csv"}
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
