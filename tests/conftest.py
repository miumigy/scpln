

import pytest
import os
from pathlib import Path
import sys
from alembic.config import main as alembic_main
import json
import sqlite3
import importlib
from app import db as appdb

@pytest.fixture
def db_setup(tmp_path, monkeypatch):
    """
    テスト関数ごとにDBをセットアップするfixture。
    1. 一時的なDBファイルを作成する。
    2. 環境変数 SCPLN_DB を設定し、アプリがテストDBを参照するようにする。
    3. Alembicを使ってDBマイグレーションを実行する。
    """
    db_path = tmp_path / "test.db"
    appdb.set_db_path(str(db_path))

    # Alembicでマイグレーションを実行
    alembic_ini_path = Path(__file__).parent.parent / "alembic.ini"
    temp_alembic_ini_path = tmp_path / "alembic.ini"
    
    with open(alembic_ini_path, "r") as src, open(temp_alembic_ini_path, "w") as dst:
        for line in src:
            if line.strip().startswith("sqlalchemy.url"):
                dst.write(f"sqlalchemy.url = sqlite:///{db_path}\n")
            else:
                dst.write(line)

    old_sys_argv = sys.argv
    try:
        sys.argv = ["alembic", "-c", str(temp_alembic_ini_path), "upgrade", "head"]
        alembic_main()
    finally:
        sys.argv = old_sys_argv
        appdb.set_db_path(None) # Reset db path after test

    # app.db モジュールをリロードして、新しい環境変数を反映させる
    importlib.reload(appdb)

    # Monkeypatch app.db._conn to ensure thread-safe connections
    def get_test_conn():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(appdb, "_conn", get_test_conn)

    yield db_path

@pytest.fixture
def seed_canonical_data(db_setup):
    """
    canonical_storage関連のテストで使用する初期データを投入する。
    db_setup fixtureに依存し、マイグレーション後のDBにデータを投入する。
    """
    db_path = db_setup
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    meta_attributes = {
        "planning_horizon": 90,
        "sources": {"psi_input": "seed.json"},
    }
    cur.execute(
        """
        INSERT INTO canonical_config_versions(
            id, name, schema_version, version_tag, status, description,
            source_config_id, metadata_json, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            100,
            "test-config",
            "canonical-1.0",
            "v-test",
            "draft",
            "unit test seed",
            None,
            json.dumps(meta_attributes, ensure_ascii=False),
            1700000000000,
            1700000000000,
        ),
    )

    cur.executemany(
        """
        INSERT INTO canonical_items(
            config_version_id, item_code, item_name, item_type, uom,
            lead_time_days, lot_size, min_order_qty, safety_stock, unit_cost,
            attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                100,
                "FG1",
                "Finished Good",
                "product",
                "unit",
                5,
                10.0,
                0.0,
                None,
                1200.0,
                json.dumps({"sales_price": 1200}, ensure_ascii=False),
            ),
            (
                100,
                "RM1",
                "Raw Material",
                "material",
                "kg",
                12,
                None,
                None,
                None,
                50.0,
                json.dumps({}, ensure_ascii=False),
            ),
        ],
    )

    cur.executemany(
        """
        INSERT INTO canonical_nodes(
            config_version_id, node_code, node_name, node_type, timezone, region,
            service_level, lead_time_days, storage_capacity, allow_storage_over_capacity,
            storage_cost_fixed, storage_over_capacity_fixed_cost,
            storage_over_capacity_variable_cost, review_period_days, attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                100,
                "STORE1",
                "Retail Store",
                "store",
                "Asia/Tokyo",
                "JP-East",
                0.9,
                2,
                200.0,
                1,
                100.0,
                10.0,
                0.5,
                7,
                json.dumps({"backorder_enabled": True}, ensure_ascii=False),
            ),
            (
                100,
                "FACT1",
                "Main Factory",
                "factory",
                "Asia/Tokyo",
                "JP-Central",
                0.95,
                5,
                500.0,
                1,
                500.0,
                20.0,
                1.0,
                14,
                json.dumps({}, ensure_ascii=False),
            ),
        ],
    )

    cur.executemany(
        """
        INSERT INTO canonical_node_items(
            config_version_id, node_code, item_code, initial_inventory, reorder_point,
            order_up_to, min_order_qty, order_multiple, safety_stock, storage_cost,
            stockout_cost, backorder_cost, lead_time_days, attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                100,
                "STORE1",
                "FG1",
                20.0,
                5.0,
                30.0,
                5.0,
                5.0,
                None,
                0.2,
                50.0,
                10.0,
                2,
                json.dumps({}, ensure_ascii=False),
            ),
            (
                100,
                "FACT1",
                "RM1",
                100.0,
                None,
                None,
                None,
                None,
                None,
                0.1,
                None,
                None,
                5,
                json.dumps({}, ensure_ascii=False),
            ),
        ],
    )

    cur.executemany(
        """
        INSERT INTO canonical_node_production(
            config_version_id, node_code, item_code, production_capacity,
            allow_over_capacity, over_capacity_fixed_cost, over_capacity_variable_cost,
            production_cost_fixed, production_cost_variable, attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                100,
                "FACT1",
                None,
                150.0,
                1,
                1000.0,
                5.0,
                2000.0,
                40.0,
                json.dumps({}, ensure_ascii=False),
            ),
            (
                100,
                "FACT1",
                "FG1",
                120.0,
                1,
                500.0,
                3.0,
                1500.0,
                35.0,
                json.dumps({}, ensure_ascii=False),
            ),
        ],
    )

    cur.execute(
        """
        INSERT INTO canonical_arcs(
            config_version_id, from_node, to_node, arc_type, lead_time_days,
            capacity_per_day, allow_over_capacity, transportation_cost_fixed,
            transportation_cost_variable, min_order_json, order_multiple_json,
            attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            100,
            "FACT1",
            "STORE1",
            "transport",
            3,
            80.0,
            1,
            200.0,
            4.0,
            json.dumps({"FG1": 10}, ensure_ascii=False),
            json.dumps({"FG1": 5}, ensure_ascii=False),
            json.dumps({}, ensure_ascii=False),
        ),
    )

    cur.execute(
        """
        INSERT INTO canonical_boms(
            config_version_id, parent_item, child_item, quantity, scrap_rate,
            attributes_json
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            100,
            "FG1",
            "RM1",
            2.0,
            None,
            json.dumps({}, ensure_ascii=False),
        ),
    )

    cur.execute(
        """
        INSERT INTO canonical_demands(
            config_version_id, node_code, item_code, bucket, demand_model,
            mean, std_dev, min_qty, max_qty, attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            100,
            "STORE1",
            "FG1",
            "2025-W01",
            "normal",
            25.0,
            3.5,
            None,
            None,
            json.dumps({}, ensure_ascii=False),
        ),
    )

    cur.execute(
        """
        INSERT INTO canonical_capacities(
            config_version_id, resource_code, resource_type, bucket, capacity,
            calendar_code, attributes_json
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            100,
            "WC1",
            "workcenter",
            "2025-W01",
            180.0,
            "CAL1",
            json.dumps({}, ensure_ascii=False),
        ),
    )

    cur.executemany(
        """
        INSERT INTO canonical_hierarchies(
            config_version_id, hierarchy_type, node_key, parent_key, level,
            sort_order, attributes_json
        ) VALUES(?,?,?,?,?,?,?)
        """,
        [
            (
                100,
                "product",
                "FG1",
                None,
                "L1",
                1,
                json.dumps({}, ensure_ascii=False),
            ),
            (
                100,
                "location",
                "STORE1",
                None,
                "Retail",
                1,
                json.dumps({}, ensure_ascii=False),
            ),
        ],
    )

    calendar_definition = {"period_cost": [{"period": "2025-01", "cost": 100}]}
    cur.execute(
        """
        INSERT INTO canonical_calendars(
            config_version_id, calendar_code, timezone, definition_json, attributes_json
        ) VALUES(?,?,?,?,?)
        """,
        (
            100,
            "CAL1",
            "Asia/Tokyo",
            json.dumps(calendar_definition, ensure_ascii=False),
            json.dumps({}, ensure_ascii=False),
        ),
    )

    conn.commit()
    conn.close()
    yield db_path
