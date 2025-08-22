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
