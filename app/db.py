import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_BASE_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _BASE_DIR / "data" / "scpln.db"
DB_PATH = os.getenv("SCPLN_DB", str(_DEFAULT_DB))
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                json_text TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        # runs テーブル（JSONはTEXT格納。将来PGではJSONB想定）
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                schema_version TEXT NOT NULL,
                summary TEXT NOT NULL,
                results TEXT NOT NULL,
                daily_profit_loss TEXT NOT NULL,
                cost_trace TEXT NOT NULL,
                config_id INTEGER,
                config_json TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC)
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runs_schema_version ON runs(schema_version)
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runs_config_id ON runs(config_id)
            """
        )
        # jobs テーブル
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                submitted_at INTEGER NOT NULL,
                started_at INTEGER,
                finished_at INTEGER,
                params_json TEXT,
                run_id TEXT,
                error TEXT
            )
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_status_submitted ON jobs(status, submitted_at DESC)
            """
        )
        # 追加カラム（既存DBへの後方互換）
        try:
            c.execute("ALTER TABLE jobs ADD COLUMN result_json TEXT")
        except Exception:
            pass
        # hierarchy master tables
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS product_hierarchy (
                key TEXT PRIMARY KEY,
                item TEXT,
                category TEXT,
                department TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS location_hierarchy (
                key TEXT PRIMARY KEY,
                region TEXT,
                country TEXT
            )
            """
        )

def create_job(job_id: str, jtype: str, status: str, submitted_at: int, params_json: str | None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO jobs(job_id, type, status, submitted_at, params_json) VALUES(?,?,?,?,?)",
            (job_id, jtype, status, submitted_at, params_json),
        )


def update_job_status(
    job_id: str,
    *,
    status: str,
    started_at: int | None = None,
    finished_at: int | None = None,
    run_id: str | None = None,
    error: str | None = None,
    submitted_at: int | None = None,
) -> None:
    with _conn() as c:
        row = c.execute("SELECT job_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return
        # Build dynamic update
        sets = ["status=?"]
        params: list = [status]
        if started_at is not None:
            sets.append("started_at=?"); params.append(started_at)
        if finished_at is not None:
            sets.append("finished_at=?"); params.append(finished_at)
        if run_id is not None:
            sets.append("run_id=?"); params.append(run_id)
        if error is not None:
            sets.append("error=?"); params.append(error)
        if submitted_at is not None:
            sets.append("submitted_at=?"); params.append(submitted_at)
        params.append(job_id)
        c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id=?", tuple(params))


def update_job_params(job_id: str, params_json: str) -> None:
    with _conn() as c:
        c.execute("UPDATE jobs SET params_json=? WHERE job_id=?", (params_json, job_id))


def get_job(job_id: str) -> Dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(status: str | None, offset: int, limit: int) -> Dict[str, Any]:
    with _conn() as c:
        where = []
        params: list = []
        if status:
            where.append("status = ?"); params.append(status)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        total = c.execute(f"SELECT COUNT(*) AS cnt FROM jobs{where_sql}", params).fetchone()["cnt"]
        rows = c.execute(
            f"SELECT * FROM jobs{where_sql} ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return {"jobs": [dict(r) for r in rows], "total": total, "offset": offset, "limit": limit}


def set_job_result(job_id: str, result_json: str) -> None:
    with _conn() as c:
        c.execute("UPDATE jobs SET result_json=? WHERE job_id=?", (result_json, job_id))


def set_product_hierarchy(mapping: Dict[str, Dict[str, str]]) -> None:
    with _conn() as c:
        c.execute("DELETE FROM product_hierarchy")
        for k, v in (mapping or {}).items():
            c.execute(
                "INSERT INTO product_hierarchy(key, item, category, department) VALUES(?,?,?,?)",
                (k, v.get("item"), v.get("category"), v.get("department")),
            )


def get_product_hierarchy() -> Dict[str, Dict[str, str]]:
    with _conn() as c:
        rows = c.execute("SELECT key, item, category, department FROM product_hierarchy").fetchall()
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            out[r["key"]] = {
                "item": r["item"],
                "category": r["category"],
                "department": r["department"],
            }
        return out


def set_location_hierarchy(mapping: Dict[str, Dict[str, str]]) -> None:
    with _conn() as c:
        c.execute("DELETE FROM location_hierarchy")
        for k, v in (mapping or {}).items():
            c.execute(
                "INSERT INTO location_hierarchy(key, region, country) VALUES(?,?,?)",
                (k, v.get("region"), v.get("country")),
            )


def get_location_hierarchy() -> Dict[str, Dict[str, str]]:
    with _conn() as c:
        rows = c.execute("SELECT key, region, country FROM location_hierarchy").fetchall()
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            out[r["key"]] = {
                "region": r["region"],
                "country": r["country"],
            }
        return out


def list_configs(limit: int = 200) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, updated_at, created_at FROM configs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_config(cfg_id: int) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        row = c.execute(
            "SELECT id, name, json_text, created_at, updated_at FROM configs WHERE id=?",
            (cfg_id,),
        ).fetchone()
        return dict(row) if row else None


def create_config(name: str, json_text: str) -> int:
    now = int(time.time() * 1000)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO configs(name, json_text, created_at, updated_at) VALUES(?,?,?,?)",
            (name, json_text, now, now),
        )
        return int(cur.lastrowid)


def update_config(cfg_id: int, name: str, json_text: str) -> None:
    now = int(time.time() * 1000)
    with _conn() as c:
        c.execute(
            "UPDATE configs SET name=?, json_text=?, updated_at=? WHERE id=?",
            (name, json_text, now, cfg_id),
        )


def delete_config(cfg_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM configs WHERE id=?", (cfg_id,))


# Initialize at import
init_db()
