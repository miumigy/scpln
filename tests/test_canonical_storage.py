import pytest
import sqlite3

from core.config.storage import (
    CanonicalConfigNotFoundError,
    get_canonical_config,
    list_canonical_versions,
    load_canonical_config_from_db,
)


def test_get_canonical_config(seed_canonical_data):

    config = get_canonical_config(100)

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


def test_list_versions_and_validation(seed_canonical_data):

    metas = list_canonical_versions(limit=5)
    assert metas[0].name == "test-config"

    config, validation = load_canonical_config_from_db(100, validate=True)
    assert validation is not None
    assert not validation.has_errors
    assert config.meta.name == "test-config"


def test_get_config_not_found(seed_canonical_data):
    with pytest.raises(CanonicalConfigNotFoundError):
        get_canonical_config(999)


def test_canonical_config_bucket_sort(seed_canonical_data):
    db_path = seed_canonical_data
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    bucket_payloads = [("M1", 30.0), ("M10", 40.0), ("M2", 35.0)]
    cur.executemany(
        """
        INSERT INTO canonical_demands(
            config_version_id, node_code, item_code, bucket, demand_model,
            mean, std_dev, min_qty, max_qty, attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (100, "STORE1", "FG1", bucket, "normal", mean, None, None, None, "{}")
            for bucket, mean in bucket_payloads
        ],
    )
    cur.executemany(
        """
        INSERT INTO canonical_capacities(
            config_version_id, resource_code, resource_type, bucket, capacity,
            calendar_code, attributes_json
        ) VALUES(?,?,?,?,?,?,?)
        """,
        [
            (100, "WC1", "workcenter", bucket, 100.0 + idx * 10, "CAL1", "{}")
            for idx, (bucket, _) in enumerate(bucket_payloads)
        ],
    )
    conn.commit()
    conn.close()

    config = get_canonical_config(100)

    month_demands = [d.bucket for d in config.demands if d.bucket.startswith("M")]
    assert month_demands == ["M1", "M2", "M10"]

    month_caps = [c.bucket for c in config.capacities if c.bucket.startswith("M")]
    assert month_caps == ["M1", "M2", "M10"]
