import importlib
import os
import sqlite3

# ensure DB init
importlib.import_module("app.db")
from app import db as appdb


def test_runs_table_has_indexes():
    path = str(appdb._DEFAULT_DB)
    assert os.path.exists(path)
    con = sqlite3.connect(path)
    try:
        cur = con.execute("PRAGMA index_list('runs')")
        names = [row[1] for row in cur.fetchall()]
        # existence check
        assert any("idx_runs_started_at" in n for n in names)
        assert any("idx_runs_schema_version" in n for n in names)
        assert any("idx_runs_config_id" in n for n in names)
    finally:
        con.close()
