#!/usr/bin/env python3
"""既存設定ソースをCanonical設定へ移行するシードスクリプト。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from core.config import CanonicalConfig, CanonicalLoaderError, load_canonical_config
from app.db import DB_PATH


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Canonical設定のシード生成")
    ap.add_argument("--name", default="canonical-seed", help="設定名")
    ap.add_argument(
        "--psi-json",
        default="static/default_input.json",
        help="PSI入力JSON（既定: static/default_input.json）",
    )
    ap.add_argument(
        "--planning-dir",
        default="samples/planning",
        help="Planning用CSVディレクトリ",
    )
    ap.add_argument(
        "--product-hierarchy",
        default="configs/product_hierarchy.json",
        help="製品階層JSON",
    )
    ap.add_argument(
        "--location-hierarchy",
        default="configs/location_hierarchy.json",
        help="ロケーション階層JSON",
    )
    ap.add_argument(
        "--output",
        default=None,
        help="Canonical設定を保存するJSONファイルパス",
    )
    ap.add_argument(
        "--save-db",
        action="store_true",
        help="canonical_config_versions* テーブルへ書き込み",
    )
    ap.add_argument(
        "--db-path",
        default=DB_PATH,
        help="SQLite DBパス（既定: SCPLN_DB or data/scpln.db）",
    )
    ap.add_argument(
        "--allow-errors",
        action="store_true",
        help="検証エラーがあっても処理を続行",
    )
    ap.add_argument(
        "--skip-validation",
        action="store_true",
        help="整合チェックを省略",
    )
    return ap.parse_args()


def _summary(config: CanonicalConfig) -> str:
    return (
        f"items={len(config.items)}, nodes={len(config.nodes)}, arcs={len(config.arcs)}, "
        f"bom={len(config.bom)}, demands={len(config.demands)}, capacities={len(config.capacities)}"
    )


def _store_to_db(config: CanonicalConfig, db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        cur = conn.cursor()
        now_ms = int(time.time() * 1000)
        meta = config.meta
        created = meta.created_at or now_ms
        updated = meta.updated_at or now_ms

        cur.execute(
            """
            INSERT INTO canonical_config_versions(
                name, schema_version, version_tag, status, description,
                source_config_id, metadata_json, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                meta.name,
                meta.schema_version,
                meta.version_tag,
                meta.status,
                meta.description,
                meta.source_config_id,
                json.dumps(meta.attributes or {}, ensure_ascii=False),
                created,
                updated,
            ),
        )
        version_id = int(cur.lastrowid)

        _insert_items(cur, version_id, config)
        _insert_nodes(cur, version_id, config)
        _insert_arcs(cur, version_id, config)
        _insert_bom(cur, version_id, config)
        _insert_demands(cur, version_id, config)
        _insert_capacities(cur, version_id, config)
        _insert_hierarchies(cur, version_id, config)
        _insert_calendars(cur, version_id, config)

        conn.commit()
        return version_id
    finally:
        conn.close()


def _insert_items(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    rows = [
        (
            version_id,
            item.code,
            item.name,
            item.item_type,
            item.uom,
            item.lead_time_days,
            item.lot_size,
            item.min_order_qty,
            item.safety_stock,
            item.unit_cost,
            json.dumps(item.attributes or {}, ensure_ascii=False),
        )
        for item in config.items
    ]
    cur.executemany(
        """
        INSERT INTO canonical_items(
            config_version_id, item_code, item_name, item_type, uom,
            lead_time_days, lot_size, min_order_qty, safety_stock, unit_cost,
            attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )


def _insert_nodes(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    node_rows = []
    inv_rows = []
    prod_rows = []
    for node in config.nodes:
        node_rows.append(
            (
                version_id,
                node.code,
                node.name,
                node.node_type,
                node.timezone,
                node.region,
                node.service_level,
                node.lead_time_days,
                node.storage_capacity,
                1 if node.allow_storage_over_capacity else 0,
                node.storage_cost_fixed,
                node.storage_over_capacity_fixed_cost,
                node.storage_over_capacity_variable_cost,
                node.review_period_days,
                json.dumps(node.attributes or {}, ensure_ascii=False),
            )
        )
        for inv in node.inventory_policies:
            inv_rows.append(
                (
                    version_id,
                    node.code,
                    inv.item_code,
                    inv.initial_inventory,
                    inv.reorder_point,
                    inv.order_up_to,
                    inv.min_order_qty,
                    inv.order_multiple,
                    inv.safety_stock,
                    inv.storage_cost,
                    inv.stockout_cost,
                    inv.backorder_cost,
                    inv.lead_time_days,
                    json.dumps(inv.attributes or {}, ensure_ascii=False),
                )
            )
        for prod in node.production_policies:
            prod_rows.append(
                (
                    version_id,
                    node.code,
                    prod.item_code,
                    prod.production_capacity,
                    1 if prod.allow_over_capacity else 0,
                    prod.over_capacity_fixed_cost,
                    prod.over_capacity_variable_cost,
                    prod.production_cost_fixed,
                    prod.production_cost_variable,
                    json.dumps(prod.attributes or {}, ensure_ascii=False),
                )
            )

    cur.executemany(
        """
        INSERT INTO canonical_nodes(
            config_version_id, node_code, node_name, node_type, timezone, region,
            service_level, lead_time_days, storage_capacity,
            allow_storage_over_capacity, storage_cost_fixed,
            storage_over_capacity_fixed_cost, storage_over_capacity_variable_cost,
            review_period_days, attributes_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        node_rows,
    )

    if inv_rows:
        cur.executemany(
            """
            INSERT INTO canonical_node_items(
                config_version_id, node_code, item_code, initial_inventory,
                reorder_point, order_up_to, min_order_qty, order_multiple,
                safety_stock, storage_cost, stockout_cost, backorder_cost,
                lead_time_days, attributes_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            inv_rows,
        )

    if prod_rows:
        cur.executemany(
            """
            INSERT INTO canonical_node_production(
                config_version_id, node_code, item_code, production_capacity,
                allow_over_capacity, over_capacity_fixed_cost,
                over_capacity_variable_cost, production_cost_fixed,
                production_cost_variable, attributes_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            prod_rows,
        )


def _insert_arcs(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    rows = [
        (
            version_id,
            arc.from_node,
            arc.to_node,
            arc.arc_type,
            arc.lead_time_days,
            arc.capacity_per_day,
            1 if arc.allow_over_capacity else 0,
            arc.transportation_cost_fixed,
            arc.transportation_cost_variable,
            json.dumps(arc.min_order_qty or {}, ensure_ascii=False),
            json.dumps(arc.order_multiple or {}, ensure_ascii=False),
            json.dumps(arc.attributes or {}, ensure_ascii=False),
        )
        for arc in config.arcs
    ]
    if rows:
        cur.executemany(
            """
            INSERT INTO canonical_arcs(
                config_version_id, from_node, to_node, arc_type, lead_time_days,
                capacity_per_day, allow_over_capacity, transportation_cost_fixed,
                transportation_cost_variable, min_order_json, order_multiple_json,
                attributes_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )


def _insert_bom(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    rows = [
        (
            version_id,
            bom.parent_item,
            bom.child_item,
            bom.quantity,
            bom.scrap_rate,
            json.dumps(bom.attributes or {}, ensure_ascii=False),
        )
        for bom in config.bom
    ]
    if rows:
        cur.executemany(
            """
            INSERT INTO canonical_boms(
                config_version_id, parent_item, child_item, quantity, scrap_rate,
                attributes_json
            ) VALUES(?,?,?,?,?,?)
            """,
            rows,
        )


def _insert_demands(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    rows = [
        (
            version_id,
            dem.node_code,
            dem.item_code,
            dem.bucket,
            dem.demand_model,
            dem.mean,
            dem.std_dev,
            dem.min_qty,
            dem.max_qty,
            json.dumps(dem.attributes or {}, ensure_ascii=False),
        )
        for dem in config.demands
    ]
    if rows:
        cur.executemany(
            """
            INSERT INTO canonical_demands(
                config_version_id, node_code, item_code, bucket, demand_model,
                mean, std_dev, min_qty, max_qty, attributes_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )


def _insert_capacities(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    rows = [
        (
            version_id,
            cap.resource_code,
            cap.resource_type,
            cap.bucket,
            cap.capacity,
            cap.calendar_code,
            json.dumps(cap.attributes or {}, ensure_ascii=False),
        )
        for cap in config.capacities
    ]
    if rows:
        cur.executemany(
            """
            INSERT INTO canonical_capacities(
                config_version_id, resource_code, resource_type, bucket, capacity,
                calendar_code, attributes_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            rows,
        )


def _insert_hierarchies(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    rows = [
        (
            version_id,
            hier.hierarchy_type,
            hier.node_key,
            hier.parent_key,
            hier.level,
            hier.sort_order,
            json.dumps(hier.attributes or {}, ensure_ascii=False),
        )
        for hier in config.hierarchies
    ]
    if rows:
        cur.executemany(
            """
            INSERT INTO canonical_hierarchies(
                config_version_id, hierarchy_type, node_key, parent_key, level,
                sort_order, attributes_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            rows,
        )


def _insert_calendars(cur: sqlite3.Cursor, version_id: int, config: CanonicalConfig) -> None:
    rows = [
        (
            version_id,
            cal.calendar_code,
            cal.timezone,
            json.dumps(cal.definition or {}, ensure_ascii=False),
            json.dumps(cal.attributes or {}, ensure_ascii=False),
        )
        for cal in config.calendars
    ]
    if rows:
        cur.executemany(
            """
            INSERT INTO canonical_calendars(
                config_version_id, calendar_code, timezone, definition_json,
                attributes_json
            ) VALUES(?,?,?,?,?)
            """,
            rows,
        )


def main() -> int:
    args = parse_args()

    psi_path = Path(args.psi_json).resolve()
    planning_dir = Path(args.planning_dir).resolve()
    prod_hierarchy = Path(args.product_hierarchy).resolve()
    loc_hierarchy = Path(args.location_hierarchy).resolve()

    try:
        config, validation = load_canonical_config(
            name=args.name,
            psi_input_path=psi_path,
            planning_dir=planning_dir,
            product_hierarchy_path=prod_hierarchy,
            location_hierarchy_path=loc_hierarchy,
            include_validation=not args.skip_validation,
        )
    except CanonicalLoaderError as exc:
        print(f"[error] ロード失敗: {exc}", file=sys.stderr)
        return 2

    if validation and validation.has_errors and not args.allow_errors:
        for issue in validation.issues:
            print(
                f"[{issue.severity}] {issue.code}: {issue.message} {issue.context}",
                file=sys.stderr,
            )
        print("検証エラーが発生したため中断しました (--allow-errorsで継続可能)", file=sys.stderr)
        return 3

    print(f"[info] Canonical設定生成完了: {_summary(config)}")
    if validation:
        warn_cnt = sum(1 for i in validation.issues if i.severity == "warning")
        err_cnt = sum(1 for i in validation.issues if i.severity == "error")
        print(f"[info] validation: errors={err_cnt}, warnings={warn_cnt}")

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fp:
            json.dump(config.model_dump(mode="json"), fp, ensure_ascii=False, indent=2)
        print(f"[info] JSONを書き出しました: {output_path}")

    if args.save_db:
        try:
            version_id = _store_to_db(config, args.db_path)
        except sqlite3.OperationalError as exc:
            print(
                f"[error] DB書き込みに失敗しました: {exc}. Alembicマイグレーションを適用してください。",
                file=sys.stderr,
            )
            return 4
        print(f"[info] DBへ保存しました: canonical_config_versions.id={version_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
