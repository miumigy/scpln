"""add planning input sets"""

from __future__ import annotations

import sqlalchemy as sa
import json
import time
from alembic import op


# revision identifiers, used by Alembic.
revision = "36858d371b14"
down_revision = "f63a4c8f02c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planning_input_sets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "config_version_id",
            sa.Integer,
            sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text, nullable=False, unique=True),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("source", sa.Text, nullable=False, server_default="csv"),
        sa.Column("created_by", sa.Text, nullable=True),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
        sa.Column("metadata_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("calendar_spec_json", sa.Text, nullable=True),
        sa.Column("planning_params_json", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_planning_input_sets_config",
        "planning_input_sets",
        ["config_version_id", "status"],
        unique=False,
    )

    op.create_table(
        "planning_family_demands",
        sa.Column(
            "input_set_id",
            sa.Integer,
            sa.ForeignKey("planning_input_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_code", sa.Text, nullable=False),
        sa.Column("period", sa.Text, nullable=False),
        sa.Column("demand", sa.Float, nullable=False, server_default="0"),
        sa.Column("source_type", sa.Text, nullable=False, server_default="canonical"),
        sa.Column("tolerance_abs", sa.Float, nullable=True),
        sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint(
            "input_set_id", "family_code", "period", name="pk_planning_family_demands"
        ),
    )

    op.create_table(
        "planning_capacity_buckets",
        sa.Column(
            "input_set_id",
            sa.Integer,
            sa.ForeignKey("planning_input_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_code", sa.Text, nullable=False),
        sa.Column(
            "resource_type", sa.Text, nullable=False, server_default="workcenter"
        ),
        sa.Column("period", sa.Text, nullable=False),
        sa.Column("capacity", sa.Float, nullable=False, server_default="0"),
        sa.Column("calendar_code", sa.Text, nullable=True),
        sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint(
            "input_set_id",
            "resource_code",
            "period",
            name="pk_planning_capacity_buckets",
        ),
    )

    op.create_table(
        "planning_mix_shares",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "input_set_id",
            sa.Integer,
            sa.ForeignKey("planning_input_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_code", sa.Text, nullable=False),
        sa.Column("sku_code", sa.Text, nullable=False),
        sa.Column("effective_from", sa.Text, nullable=True),
        sa.Column("effective_to", sa.Text, nullable=True),
        sa.Column("share", sa.Float, nullable=False, server_default="0"),
        sa.Column("weight_source", sa.Text, nullable=False, server_default="manual"),
        sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
        sa.UniqueConstraint(
            "input_set_id",
            "family_code",
            "sku_code",
            "effective_from",
            name="uq_planning_mix_shares_key",
        ),
    )

    op.create_table(
        "planning_inventory_snapshots",
        sa.Column(
            "input_set_id",
            sa.Integer,
            sa.ForeignKey("planning_input_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_code", sa.Text, nullable=False),
        sa.Column("item_code", sa.Text, nullable=False),
        sa.Column("initial_qty", sa.Float, nullable=False, server_default="0"),
        sa.Column("reorder_point", sa.Float, nullable=True),
        sa.Column("order_up_to", sa.Float, nullable=True),
        sa.Column("safety_stock", sa.Float, nullable=True),
        sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint(
            "input_set_id",
            "node_code",
            "item_code",
            name="pk_planning_inventory_snapshots",
        ),
    )

    op.create_table(
        "planning_inbound_orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "input_set_id",
            sa.Integer,
            sa.ForeignKey("planning_input_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("po_id", sa.Text, nullable=True),
        sa.Column("item_code", sa.Text, nullable=False),
        sa.Column("source_node", sa.Text, nullable=True),
        sa.Column("dest_node", sa.Text, nullable=True),
        sa.Column("due_date", sa.Text, nullable=False),
        sa.Column("qty", sa.Float, nullable=False, server_default="0"),
        sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
        sa.UniqueConstraint(
            "input_set_id", "po_id", name="uq_planning_inbound_orders_po"
        ),
    )

    op.create_table(
        "planning_period_metrics",
        sa.Column(
            "input_set_id",
            sa.Integer,
            sa.ForeignKey("planning_input_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_code", sa.Text, nullable=False),
        sa.Column("period", sa.Text, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint(
            "input_set_id", "metric_code", "period", name="pk_planning_period_metrics"
        ),
    )

    _migrate_planning_payload()


def downgrade() -> None:
    _restore_planning_payload()
    op.drop_table("planning_period_metrics")
    op.drop_table("planning_inbound_orders")
    op.drop_table("planning_inventory_snapshots")
    op.drop_table("planning_mix_shares")
    op.drop_table("planning_capacity_buckets")
    op.drop_table("planning_family_demands")
    op.drop_index("idx_planning_input_sets_config", table_name="planning_input_sets")
    op.drop_table("planning_input_sets")


def _migrate_planning_payload() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, metadata_json, created_at, updated_at FROM canonical_config_versions"
        )
    ).fetchall()
    now = int(time.time() * 1000)
    for row in rows:
        metadata = _safe_json_load(row.metadata_json)
        payload = metadata.get("planning_payload") or {}
        if not payload:
            continue
        label = f"default_v{row.id}"
        calendar_spec = payload.get("planning_calendar")
        insert_result = conn.execute(
            sa.text(
                """
                INSERT INTO planning_input_sets(
                    config_version_id, label, status, source, created_by,
                    created_at, updated_at, metadata_json, calendar_spec_json,
                    planning_params_json
                ) VALUES(:vid, :label, :status, :source, NULL, :created, :updated, :meta, :calendar, :params)
                """
            ),
            {
                "vid": row.id,
                "label": label,
                "status": "ready",
                "source": "legacy",
                "created": row.created_at or now,
                "updated": row.updated_at or now,
                "meta": json.dumps(
                    {"migrated_from": "planning_payload"}, ensure_ascii=False
                ),
                "calendar": json.dumps(calendar_spec or {}, ensure_ascii=False),
                "params": json.dumps(
                    payload.get("planning_params") or {}, ensure_ascii=False
                ),
            },
        )
        input_set_id = insert_result.lastrowid
        _bulk_insert_family_demands(conn, input_set_id, payload.get("demand_family"))
        _bulk_insert_capacity(conn, input_set_id, payload.get("capacity"))
        _bulk_insert_mix(conn, input_set_id, payload.get("mix_share"))
        _bulk_insert_inventory(conn, input_set_id, payload.get("inventory"))
        _bulk_insert_open_po(conn, input_set_id, payload.get("open_po"))
        _bulk_insert_period_metric(
            conn, input_set_id, payload.get("period_cost"), "cost"
        )
        _bulk_insert_period_metric(
            conn, input_set_id, payload.get("period_score"), "score"
        )
        metadata.pop("planning_payload", None)
        metadata["planning_inputs_migrated"] = True
        conn.execute(
            sa.text(
                "UPDATE canonical_config_versions SET metadata_json = :meta WHERE id = :vid"
            ),
            {"meta": json.dumps(metadata, ensure_ascii=False), "vid": row.id},
        )


def _restore_planning_payload() -> None:
    conn = op.get_bind()
    processed = set()
    rows = conn.execute(
        sa.text(
            """
            SELECT * FROM planning_input_sets
            ORDER BY updated_at DESC
            """
        )
    ).fetchall()
    for row in rows:
        vid = row.config_version_id
        if vid in processed:
            continue
        payload = {
            "demand_family": _fetch_family_for_payload(conn, row.id),
            "capacity": _fetch_capacity_for_payload(conn, row.id),
            "mix_share": _fetch_mix_for_payload(conn, row.id),
            "inventory": _fetch_inventory_for_payload(conn, row.id),
            "open_po": _fetch_open_po_for_payload(conn, row.id),
            "period_cost": _fetch_metric_rows(conn, row.id, "cost"),
            "period_score": _fetch_metric_rows(conn, row.id, "score"),
        }
        calendar = _safe_json_load(row.calendar_spec_json)
        if calendar:
            payload["planning_calendar"] = calendar

        meta_row = conn.execute(
            sa.text(
                "SELECT metadata_json FROM canonical_config_versions WHERE id = :vid"
            ),
            {"vid": vid},
        ).fetchone()
        metadata = _safe_json_load(meta_row.metadata_json if meta_row else None)
        metadata["planning_payload"] = payload
        metadata.pop("planning_inputs_migrated", None)
        conn.execute(
            sa.text(
                "UPDATE canonical_config_versions SET metadata_json = :meta WHERE id = :vid"
            ),
            {"meta": json.dumps(metadata, ensure_ascii=False), "vid": vid},
        )
        processed.add(vid)


def _safe_json_load(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _bulk_insert_family_demands(conn, input_set_id, rows):
    items = []
    for row in rows or []:
        family = row.get("family")
        period = row.get("period")
        if not family or not period:
            continue
        try:
            demand = float(row.get("demand") or 0)
        except Exception:
            demand = 0.0
        items.append(
            {
                "input_set_id": input_set_id,
                "family_code": family,
                "period": period,
                "demand": demand,
            }
        )
    if items:
        conn.execute(
            sa.text(
                """
                INSERT INTO planning_family_demands(
                    input_set_id, family_code, period, demand
                ) VALUES(:input_set_id, :family_code, :period, :demand)
                """
            ),
            items,
        )


def _bulk_insert_capacity(conn, input_set_id, rows):
    items = []
    for row in rows or []:
        resource = row.get("workcenter") or row.get("resource_code")
        period = row.get("period")
        if not resource or not period:
            continue
        try:
            capacity = float(row.get("capacity") or 0)
        except Exception:
            capacity = 0.0
        items.append(
            {
                "input_set_id": input_set_id,
                "resource_code": resource,
                "resource_type": row.get("resource_type") or "workcenter",
                "period": period,
                "capacity": capacity,
            }
        )
    if items:
        conn.execute(
            sa.text(
                """
                INSERT INTO planning_capacity_buckets(
                    input_set_id, resource_code, resource_type, period, capacity
                ) VALUES(:input_set_id, :resource_code, :resource_type, :period, :capacity)
                """
            ),
            items,
        )


def _bulk_insert_mix(conn, input_set_id, rows):
    items = []
    for row in rows or []:
        family = row.get("family") or row.get("family_code")
        sku = row.get("sku") or row.get("sku_code")
        if not family or not sku:
            continue
        try:
            share = float(row.get("share") or 0)
        except Exception:
            share = 0.0
        items.append(
            {
                "input_set_id": input_set_id,
                "family_code": family,
                "sku_code": sku,
                "share": share,
                "effective_from": None,
                "effective_to": None,
                "weight_source": "legacy",
            }
        )
    if items:
        conn.execute(
            sa.text(
                """
                INSERT INTO planning_mix_shares(
                    input_set_id, family_code, sku_code, share, effective_from,
                    effective_to, weight_source
                ) VALUES(:input_set_id, :family_code, :sku_code, :share, :effective_from, :effective_to, :weight_source)
                """
            ),
            items,
        )


def _bulk_insert_inventory(conn, input_set_id, rows):
    items = []
    for row in rows or []:
        item = row.get("item") or row.get("item_code")
        node = row.get("loc") or row.get("node") or row.get("node_code")
        if not item or not node:
            continue
        try:
            qty = float(row.get("qty") or row.get("initial_qty") or 0)
        except Exception:
            qty = 0.0
        items.append(
            {
                "input_set_id": input_set_id,
                "node_code": node,
                "item_code": item,
                "initial_qty": qty,
            }
        )
    if items:
        conn.execute(
            sa.text(
                """
                INSERT INTO planning_inventory_snapshots(
                    input_set_id, node_code, item_code, initial_qty
                ) VALUES(:input_set_id, :node_code, :item_code, :initial_qty)
                """
            ),
            items,
        )


def _bulk_insert_open_po(conn, input_set_id, rows):
    items = []
    for row in rows or []:
        item = row.get("item") or row.get("item_code")
        due = row.get("due") or row.get("due_date")
        if not item or not due:
            continue
        try:
            qty = float(row.get("qty") or 0)
        except Exception:
            qty = 0.0
        items.append(
            {
                "input_set_id": input_set_id,
                "po_id": row.get("po_id"),
                "item_code": item,
                "due_date": due,
                "qty": qty,
            }
        )
    if items:
        conn.execute(
            sa.text(
                """
                INSERT INTO planning_inbound_orders(
                    input_set_id, po_id, item_code, due_date, qty
                ) VALUES(:input_set_id, :po_id, :item_code, :due_date, :qty)
                """
            ),
            items,
        )


def _bulk_insert_period_metric(conn, input_set_id, rows, metric_code):
    items = []
    for row in rows or []:
        period = row.get("period")
        if not period:
            continue
        try:
            value = float(
                row.get("cost" if metric_code == "cost" else "score")
                or row.get("value")
                or 0
            )
        except Exception:
            value = 0.0
        items.append(
            {
                "input_set_id": input_set_id,
                "metric_code": metric_code,
                "period": period,
                "value": value,
            }
        )
    if items:
        conn.execute(
            sa.text(
                """
                INSERT INTO planning_period_metrics(
                    input_set_id, metric_code, period, value
                ) VALUES(:input_set_id, :metric_code, :period, :value)
                """
            ),
            items,
        )


def _fetch_metric_rows(conn, input_set_id, metric_code):
    result = conn.execute(
        sa.text(
            """
            SELECT period, value FROM planning_period_metrics
            WHERE input_set_id = :id AND metric_code = :metric
            """
        ),
        {"id": input_set_id, "metric": metric_code},
    ).fetchall()
    column = "cost" if metric_code == "cost" else "score"
    return [{"period": row.period, column: row.value} for row in result]


def _fetch_family_for_payload(conn, input_set_id):
    rows = conn.execute(
        sa.text(
            """
            SELECT family_code, period, demand
            FROM planning_family_demands
            WHERE input_set_id = :id
            ORDER BY family_code, period
            """
        ),
        {"id": input_set_id},
    ).fetchall()
    return [
        {"family": row.family_code, "period": row.period, "demand": row.demand}
        for row in rows
    ]


def _fetch_capacity_for_payload(conn, input_set_id):
    rows = conn.execute(
        sa.text(
            """
            SELECT resource_code, period, capacity
            FROM planning_capacity_buckets
            WHERE input_set_id = :id
            ORDER BY resource_code, period
            """
        ),
        {"id": input_set_id},
    ).fetchall()
    return [
        {
            "workcenter": row.resource_code,
            "period": row.period,
            "capacity": row.capacity,
        }
        for row in rows
    ]


def _fetch_mix_for_payload(conn, input_set_id):
    rows = conn.execute(
        sa.text(
            """
            SELECT family_code, sku_code, share
            FROM planning_mix_shares
            WHERE input_set_id = :id
            ORDER BY family_code, sku_code
            """
        ),
        {"id": input_set_id},
    ).fetchall()
    return [
        {"family": row.family_code, "sku": row.sku_code, "share": row.share}
        for row in rows
    ]


def _fetch_inventory_for_payload(conn, input_set_id):
    rows = conn.execute(
        sa.text(
            """
            SELECT node_code, item_code, initial_qty
            FROM planning_inventory_snapshots
            WHERE input_set_id = :id
            ORDER BY node_code, item_code
            """
        ),
        {"id": input_set_id},
    ).fetchall()
    return [
        {"loc": row.node_code, "item": row.item_code, "qty": row.initial_qty}
        for row in rows
    ]


def _fetch_open_po_for_payload(conn, input_set_id):
    rows = conn.execute(
        sa.text(
            """
            SELECT item_code, due_date, qty
            FROM planning_inbound_orders
            WHERE input_set_id = :id
            ORDER BY due_date, item_code
            """
        ),
        {"id": input_set_id},
    ).fetchall()
    return [
        {"item": row.item_code, "due": row.due_date, "qty": row.qty} for row in rows
    ]
