import os
import json
import sqlite3
import time
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


_BASE_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _BASE_DIR / "data" / "scpln.db"
_current_db_path: str | None = None

_logger = logging.getLogger(__name__)
_init_lock = threading.Lock()
_initialized = False

Path(_DEFAULT_DB).parent.mkdir(parents=True, exist_ok=True)


def set_db_path(path: str) -> None:
    global _current_db_path
    _current_db_path = path


def _db_path() -> str:
    path = (
        _current_db_path
        if _current_db_path is not None
        else os.getenv("SCPLN_DB", str(_DEFAULT_DB))
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn() -> sqlite3.Connection:
    db_path_to_use = _db_path()
    conn = sqlite3.connect(db_path_to_use)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force: bool = False) -> None:
    """Alembicマイグレーションを適用し、SQLiteスキーマを最新化する。"""
    _logger.info(
        "DB URL: %s | SCPLN_DB: %s",
        os.environ.get("DATABASE_URL"),
        os.environ.get("SCPLN_DB"),
    )

    global _initialized
    if _initialized and not force:
        return

    with _init_lock:
        if _initialized and not force:
            return

        ini_path = _BASE_DIR / "alembic.ini"
        script_location = _BASE_DIR / "alembic"

        if not ini_path.exists() or not script_location.exists():
            _logger.warning(
                "DB初期化をスキップします: alembic設定が見つかりません (ini=%s, script=%s)",
                ini_path,
                script_location,
            )
            _initialized = True
            return

        try:
            from alembic.config import Config
            from alembic import command
        except Exception as exc:  # pragma: no cover - alembic未導入の異常系
            _logger.error("alembicの読み込みに失敗しました: %s", exc)
            raise

        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(script_location))
        db_path_to_use = _db_path()
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path_to_use}")

        _logger.info("DBマイグレーションを適用します: %s", db_path_to_use)
        try:
            command.upgrade(cfg, "head")
        except Exception as exc:
            _logger.error("DBマイグレーションに失敗しました: %s", exc)
            raise
        else:
            _initialized = True
            _logger.info("DBマイグレーションが完了しました")


def create_job(
    job_id: str, jtype: str, status: str, submitted_at: int, params_json: str | None
) -> None:
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
            sets.append("started_at=?")
            params.append(started_at)
        if finished_at is not None:
            sets.append("finished_at=?")
            params.append(finished_at)
        if run_id is not None:
            sets.append("run_id=?")
            params.append(run_id)
        if error is not None:
            sets.append("error=?")
            params.append(error)
        if submitted_at is not None:
            sets.append("submitted_at=?")
            params.append(submitted_at)
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
            where.append("status = ?")
            params.append(status)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        total = c.execute(
            f"SELECT COUNT(*) AS cnt FROM jobs{where_sql}", params
        ).fetchone()["cnt"]
        rows = c.execute(
            f"SELECT * FROM jobs{where_sql} ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return {
            "jobs": [dict(r) for r in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }


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
        rows = c.execute(
            "SELECT key, item, category, department FROM product_hierarchy"
        ).fetchall()
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
        rows = c.execute(
            "SELECT key, region, country FROM location_hierarchy"
        ).fetchall()
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            out[r["key"]] = {
                "region": r["region"],
                "country": r["country"],
            }
        return out


def count_table_rows(table_name: str) -> int:
    """指定されたテーブルの総行数を返す。"""
    # テーブル名のサニタイズ（簡易的）
    if not table_name.replace("_", "").isalnum():
        raise ValueError(f"Invalid table name: {table_name}")
    with _conn() as c:
        row = c.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}").fetchone()
        return int(row["cnt"] if row else 0)


# --- Scenarios (phase2 foundation) ---
def list_scenarios(limit: int = 200) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, parent_id, tag, locked, updated_at, created_at FROM scenarios ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_scenario(sid: int) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM scenarios WHERE id=?", (sid,)).fetchone()
        return dict(row) if row else None


def create_scenario(
    name: str,
    parent_id: Optional[int],
    tag: Optional[str],
    description: Optional[str],
    locked: bool = False,
) -> int:
    now = int(time.time() * 1000)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO scenarios(name, parent_id, tag, description, locked, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (name, parent_id, tag, description, 1 if locked else 0, now, now),
        )
        return int(cur.lastrowid)
