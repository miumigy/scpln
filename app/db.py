import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_PATH = os.getenv("SCPLN_DB", str(Path("data") / "scpln.db"))
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
