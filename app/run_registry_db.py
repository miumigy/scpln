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

    # ページング/ソート/フィルタ対応（/runs 用）
    def list_page(
        self,
        offset: int,
        limit: int,
        sort: str = "started_at",
        order: str = "desc",
        schema_version: Optional[str] = None,
        config_id: Optional[int] = None,
        detail: bool = False,
    ) -> Dict[str, Any]:
        sort_keys = {"started_at", "duration_ms", "schema_version"}
        if sort not in sort_keys:
            sort = "started_at"
        order = "DESC" if order.lower() != "asc" else "ASC"
        where = []
        params: List[Any] = []
        if schema_version is not None:
            where.append("schema_version = ?")
            params.append(schema_version)
        if config_id is not None:
            where.append("config_id = ?")
            params.append(config_id)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with _conn() as c:
            total = c.execute(f"SELECT COUNT(*) as cnt FROM runs{where_sql}", params).fetchone()[
                "cnt"
            ]
            cols = "*" if detail else "run_id, started_at, duration_ms, schema_version, summary, config_id"
            rows = c.execute(
                f"SELECT {cols} FROM runs{where_sql} ORDER BY {sort} {order}, run_id {order} LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            if detail:
                data = [self._row_to_rec(r) for r in rows]
            else:
                # 軽量メタ（summaryはTEXT→dict化）
                data = []
                for r in rows:
                    data.append(
                        {
                            "run_id": r["run_id"],
                            "started_at": r["started_at"],
                            "duration_ms": r["duration_ms"],
                            "schema_version": r["schema_version"],
                            "summary": json.loads(r["summary"] or "{}"),
                            "config_id": r["config_id"],
                        }
                    )
        return {"runs": data, "total": total, "offset": offset, "limit": limit}

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

    def delete(self, run_id: str) -> None:
        with _conn() as c:
            c.execute("DELETE FROM runs WHERE run_id=?", (run_id,))

    def cleanup_by_capacity(self, max_rows: int) -> None:
        if max_rows <= 0:
            return
        with _conn() as c:
            cnt = c.execute("SELECT COUNT(*) AS cnt FROM runs").fetchone()["cnt"]
            if cnt <= max_rows:
                return
            # 古い順に超過分を削除
            to_delete = c.execute(
                "SELECT run_id FROM runs ORDER BY started_at DESC, run_id DESC LIMIT -1 OFFSET ?",
                (max_rows,),
            ).fetchall()
            ids = [r["run_id"] for r in to_delete]
            for rid in ids:
                c.execute("DELETE FROM runs WHERE run_id=?", (rid,))
