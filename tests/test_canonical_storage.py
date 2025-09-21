import json
import sqlite3
from pathlib import Path

import pytest

from core.config.storage import (
    CanonicalConfigNotFoundError,
    get_canonical_config,
    list_canonical_versions,
    load_canonical_config_from_db,
)


def _prepare_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "canonical_storage.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE canonical_config_versions (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            version_tag TEXT,
            status TEXT NOT NULL,
            description TEXT,
            source_config_id INTEGER,
            metadata_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE canonical_items (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            item_name TEXT,
            item_type TEXT NOT NULL,
            uom TEXT NOT NULL,
            lead_time_days INTEGER,
            lot_size REAL,
            min_order_qty REAL,
            safety_stock REAL,
            unit_cost REAL,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_nodes (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            node_code TEXT NOT NULL,
            node_name TEXT,
            node_type TEXT NOT NULL,
            timezone TEXT,
            region TEXT,
            service_level REAL,
            lead_time_days INTEGER,
            storage_capacity REAL,
            allow_storage_over_capacity INTEGER NOT NULL,
            storage_cost_fixed REAL,
            storage_over_capacity_fixed_cost REAL,
            storage_over_capacity_variable_cost REAL,
            review_period_days INTEGER,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_node_items (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            node_code TEXT NOT NULL,
            item_code TEXT NOT NULL,
            initial_inventory REAL,
            reorder_point REAL,
            order_up_to REAL,
            min_order_qty REAL,
            order_multiple REAL,
            safety_stock REAL,
            storage_cost REAL,
            stockout_cost REAL,
            backorder_cost REAL,
            lead_time_days INTEGER,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_node_production (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            node_code TEXT NOT NULL,
            item_code TEXT,
            production_capacity REAL,
            allow_over_capacity INTEGER NOT NULL,
            over_capacity_fixed_cost REAL,
            over_capacity_variable_cost REAL,
            production_cost_fixed REAL,
            production_cost_variable REAL,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_arcs (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            arc_type TEXT NOT NULL,
            lead_time_days INTEGER,
            capacity_per_day REAL,
            allow_over_capacity INTEGER NOT NULL,
            transportation_cost_fixed REAL,
            transportation_cost_variable REAL,
            min_order_json TEXT NOT NULL,
            order_multiple_json TEXT NOT NULL,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_boms (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            parent_item TEXT NOT NULL,
            child_item TEXT NOT NULL,
            quantity REAL,
            scrap_rate REAL,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_demands (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            node_code TEXT NOT NULL,
            item_code TEXT NOT NULL,
            bucket TEXT NOT NULL,
            demand_model TEXT NOT NULL,
            mean REAL,
            std_dev REAL,
            min_qty REAL,
            max_qty REAL,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_capacities (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            resource_code TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            bucket TEXT NOT NULL,
            capacity REAL,
            calendar_code TEXT,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_hierarchies (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            hierarchy_type TEXT NOT NULL,
            node_key TEXT NOT NULL,
            parent_key TEXT,
            level TEXT,
            sort_order INTEGER,
            attributes_json TEXT NOT NULL
        );
        CREATE TABLE canonical_calendars (
            id INTEGER PRIMARY KEY,
            config_version_id INTEGER NOT NULL,
            calendar_code TEXT NOT NULL,
            timezone TEXT,
            definition_json TEXT NOT NULL,
            attributes_json TEXT NOT NULL
        );
        """
    )

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
    return db_path


def test_get_canonical_config(tmp_path):
    db_path = _prepare_db(tmp_path)

    config = get_canonical_config(100, db_path=str(db_path))

    assert config.meta.version_id == 100
    assert config.meta.attributes["planning_horizon"] == 90

    product_codes = {item.code for item in config.items}
    assert product_codes == {"FG1", "RM1"}

    store = next(node for node in config.nodes if node.code == "STORE1")
    assert store.service_level == 0.9
    assert store.inventory_policies[0].item_code == "FG1"

    factory = next(node for node in config.nodes if node.code == "FACT1")
    assert any(policy.item_code == "FG1" for policy in factory.production_policies)

    arc = config.arcs[0]
    assert arc.from_node == "FACT1" and arc.to_node == "STORE1"
    assert arc.min_order_qty["FG1"] == 10

    demand = config.demands[0]
    assert demand.mean == 25.0 and demand.demand_model == "normal"

    assert config.calendars[0].calendar_code == "CAL1"


def test_list_versions_and_validation(tmp_path):
    db_path = _prepare_db(tmp_path)

    metas = list_canonical_versions(db_path=str(db_path), limit=5)
    assert metas[0].name == "test-config"

    config, validation = load_canonical_config_from_db(
        100, db_path=str(db_path), validate=True
    )
    assert validation is not None
    assert not validation.has_errors
    assert config.meta.name == "test-config"


def test_get_config_not_found(tmp_path):
    db_path = _prepare_db(tmp_path)
    with pytest.raises(CanonicalConfigNotFoundError):
        get_canonical_config(999, db_path=str(db_path))
