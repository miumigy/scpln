import json
import time
from typing import Any, Dict, List, Optional

from .db import _conn


class RunRegistryDB:
    def put(self, run_id: str, payload: Dict[str, Any]) -> None:
        now = int(time.time() * 1000)
        with _conn() as c:
            row = c.execute(
                "SELECT run_id FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            doc = {
                "run_id": run_id,
                "started_at": int(payload.get("started_at") or now),
                "duration_ms": int(payload.get("duration_ms") or 0),
                "schema_version": str(payload.get("schema_version") or "1.0"),
                "summary": json.dumps(payload.get("summary") or {}, ensure_ascii=False),
                "results": json.dumps(payload.get("results") or [], ensure_ascii=False),
                "daily_profit_loss": json.dumps(
                    payload.get("daily_profit_loss") or [], ensure_ascii=False
                ),
                "cost_trace": json.dumps(
                    payload.get("cost_trace") or [], ensure_ascii=False
                ),
                "config_id": payload.get("config_id"),
                "config_json": (
                    json.dumps(payload.get("config_json"))
                    if payload.get("config_json") is not None
                    else None
                ),
                "created_at": int(payload.get("started_at") or now),
                "updated_at": now,
            }
            if row:
                c.execute(
                    """
                    UPDATE runs SET started_at=?, duration_ms=?, schema_version=?, summary=?, results=?,
                        daily_profit_loss=?, cost_trace=?, config_id=?, config_json=?, updated_at=?
                    WHERE run_id=?
                    """,
                    (
                        doc["started_at"],
                        doc["duration_ms"],
                        doc["schema_version"],
                        doc["summary"],
                        doc["results"],
                        doc["daily_profit_loss"],
                        doc["cost_trace"],
                        doc["config_id"],
                        doc["config_json"],
                        doc["updated_at"],
                        run_id,
                    ),
                )
            else:
                c.execute(
                    """
                    INSERT INTO runs(run_id, started_at, duration_ms, schema_version, summary, results,
                        daily_profit_loss, cost_trace, config_id, config_json, created_at, updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        doc["run_id"],
                        doc["started_at"],
                        doc["duration_ms"],
                        doc["schema_version"],
                        doc["summary"],
                        doc["results"],
                        doc["daily_profit_loss"],
                        doc["cost_trace"],
                        doc["config_id"],
                        doc["config_json"],
                        doc["created_at"],
                        doc["updated_at"],
                    ),
                )

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            return self._row_to_rec(row) if row else None

    def list_ids(self) -> List[str]:
        with _conn() as c:
            rows = c.execute(
                "SELECT run_id FROM runs ORDER BY started_at DESC, run_id DESC"
            ).fetchall()
            return [r["run_id"] for r in rows]

    def list(self) -> List[Dict[str, Any]]:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM runs ORDER BY started_at DESC, run_id DESC"
            ).fetchall()
            return [self._row_to_rec(r) for r in rows]

    @staticmethod
    def _row_to_rec(row) -> Dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "started_at": row["started_at"],
            "duration_ms": row["duration_ms"],
            "schema_version": row["schema_version"],
            "summary": json.loads(row["summary"] or "{}"),
            "results": json.loads(row["results"] or "[]"),
            "daily_profit_loss": json.loads(row["daily_profit_loss"] or "[]"),
            "cost_trace": json.loads(row["cost_trace"] or "[]"),
            "config_id": row["config_id"],
            "config_json": (
                json.loads(row["config_json"]) if row["config_json"] else None
            ),
        }
