from app import db as appdb


def test_runs_table_has_indexes(db_setup):
    with appdb._conn() as con:
        cur = con.execute("PRAGMA index_list('runs')")
        names = [row[1] for row in cur.fetchall()]
        # existence check
        assert any("idx_runs_started_at" in n for n in names)
        assert any("idx_runs_schema_version" in n for n in names)
        assert any("idx_runs_config_id" in n for n in names)
        assert any("idx_runs_scenario_id" in n for n in names)
