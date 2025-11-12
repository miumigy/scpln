import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from .db import _conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """指定テーブルの存在を確認し、使用済みコネクションを確実に閉じる。"""
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
                "config_version_id": payload.get("config_version_id"),
                "scenario_id": payload.get("scenario_id"),
                "plan_version_id": payload.get("plan_version_id"),
                "plan_job_id": payload.get("plan_job_id"),
                "input_set_label": payload.get("input_set_label"),
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
                        daily_profit_loss=?, cost_trace=?, config_id=?, config_version_id=?, scenario_id=?, plan_version_id=?, plan_job_id=?, config_json=?, updated_at=?, input_set_label=?
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
                        doc["config_version_id"],
                        doc["scenario_id"],
                        doc["plan_version_id"],
                        doc["plan_job_id"],
                        doc["config_json"],
                        doc["updated_at"],
                        doc["input_set_label"],
                        run_id,
                    ),
                )
            else:
                c.execute(
                    """
                    INSERT INTO runs(run_id, started_at, duration_ms, schema_version, summary, results,
                        daily_profit_loss, cost_trace, config_id, config_version_id, scenario_id, plan_version_id, plan_job_id, config_json, created_at, updated_at, input_set_label)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                        doc["config_version_id"],
                        doc["scenario_id"],
                        doc["plan_version_id"],
                        doc["plan_job_id"],
                        doc["config_json"],
                        doc["created_at"],
                        doc["updated_at"],
                        doc["input_set_label"],
                    ),
                )
        try:
            # Log what we saved (booleans only, to avoid large payloads)
            import logging

            logging.debug(
                "run_saved",
                extra={
                    "event": "run_saved",
                    "run_id": run_id,
                    "config_id": payload.get("config_id"),
                    "config_version_id": payload.get("config_version_id"),
                    "config_json_present": bool(payload.get("config_json")),
                },
            )
        except Exception:
            pass
        # オプション: 容量上限制御（古いRunのクリーンアップ）
        try:
            max_rows = int(os.getenv("RUNS_DB_MAX_ROWS", "0") or 0)
            if max_rows > 0:
                self.cleanup_by_capacity(max_rows)
        except Exception:
            pass

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            # 後方互換: メモリ実装は見つからない場合に {} を返すコードパスがあるため、
            # DB実装でも {} を返して同等に扱えるようにする
            return self._row_to_rec(row) if row else {}

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
        scenario_id: Optional[int] = None,
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
        if scenario_id is not None:
            where.append("scenario_id = ?")
            params.append(scenario_id)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with _conn() as c:
            total = c.execute(
                f"SELECT COUNT(*) as cnt FROM runs{where_sql}", params
            ).fetchone()["cnt"]
            cols = (
                "*"
                if detail
                else "run_id, started_at, duration_ms, schema_version, summary, config_id, config_version_id, scenario_id, plan_version_id, input_set_label, config_json, created_at, updated_at"
            )
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
                    summary_obj = json.loads(r["summary"] or "{}")
                    data.append(
                        {
                            "run_id": r["run_id"],
                            "started_at": r["started_at"],
                            "duration_ms": r["duration_ms"],
                            "schema_version": r["schema_version"],
                            "summary": summary_obj,
                            "config_id": r["config_id"],
                            "config_version_id": (
                                r["config_version_id"]
                                if "config_version_id" in r.keys()
                                else None
                            ),
                            "scenario_id": r["scenario_id"],
                            "plan_version_id": (
                                r["plan_version_id"]
                                if "plan_version_id" in r.keys()
                                else None
                            ),
                            "input_set_label": r["input_set_label"],
                            "config_json": (
                                json.loads(r["config_json"])
                                if r["config_json"]
                                else None
                            ),
                            "created_at": r["created_at"],
                            "updated_at": r["updated_at"],
                        }
                    )
        return {"runs": data, "total": total, "offset": offset, "limit": limit}

    @staticmethod
    def _row_to_rec(row) -> Dict[str, Any]:
        summary_obj = json.loads(row["summary"] or "{}")
        return {
            "run_id": row["run_id"],
            "started_at": row["started_at"],
            "duration_ms": row["duration_ms"],
            "schema_version": row["schema_version"],
            "summary": summary_obj,
            "results": json.loads(row["results"] or "[]"),
            "daily_profit_loss": json.loads(row["daily_profit_loss"] or "[]"),
            "cost_trace": json.loads(row["cost_trace"] or "[]"),
            "config_id": row["config_id"],
            "config_version_id": (
                row["config_version_id"] if "config_version_id" in row.keys() else None
            ),
            "scenario_id": row["scenario_id"],
            "plan_version_id": (
                row["plan_version_id"]
                if "plan_version_id" in row.keys()
                else summary_obj.get("_plan_version_id")
            ),
            "config_json": (
                json.loads(row["config_json"]) if row["config_json"] else None
            ),
            "input_set_label": row["input_set_label"],
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
