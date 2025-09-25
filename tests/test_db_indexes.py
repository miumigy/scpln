import importlib
import os
import pytest
from pathlib import Path

# ensure DB init
importlib.import_module("app.db")
from app import db as appdb

from alembic.config import Config
from alembic import command


@pytest.fixture(name="db_setup_for_indexes")
def db_setup_for_indexes_fixture(tmp_path: Path):
    db_path = tmp_path / "test_indexes.sqlite"
    os.environ["SCPLN_DB"] = str(db_path)

    # Reload app.db to pick up new SCPLN_DB env var
    importlib.reload(appdb)

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("script_location", "alembic")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")
    # Alembicの後処理でアプリ側の初期化ロジックを流し、索引を確実に生成する
    appdb.init_db()

    yield

    del os.environ["SCPLN_DB"]


def test_runs_table_has_indexes(db_setup_for_indexes):
    with appdb._conn() as con:  # _conn()を使って接続を取得
        cur = con.execute("PRAGMA index_list('runs')")
        names = [row[1] for row in cur.fetchall()]
        # existence check
        assert any("idx_runs_started_at" in n for n in names)
        assert any("idx_runs_schema_version" in n for n in names)
        assert any("idx_runs_config_id" in n for n in names)
