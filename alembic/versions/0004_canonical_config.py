"""Canonical設定テーブル追加"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0004_canonical_config"
down_revision = "0003_runs_scenario_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not insp.has_table("canonical_config_versions"):
        op.create_table(
            "canonical_config_versions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column(
                "schema_version",
                sa.Text,
                nullable=False,
                server_default="canonical-1.0",
            ),
            sa.Column("version_tag", sa.Text, nullable=True),
            sa.Column("status", sa.Text, nullable=False, server_default="draft"),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("source_config_id", sa.Integer, nullable=True),
            sa.Column("metadata_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Integer, nullable=False),
        )

    if not insp.has_table("canonical_items"):
        op.create_table(
            "canonical_items",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("item_code", sa.Text, nullable=False),
            sa.Column("item_name", sa.Text, nullable=True),
            sa.Column("item_type", sa.Text, nullable=False, server_default="product"),
            sa.Column("uom", sa.Text, nullable=False, server_default="unit"),
            sa.Column("lead_time_days", sa.Integer, nullable=False, server_default="0"),
            sa.Column("lot_size", sa.Float, nullable=True),
            sa.Column("min_order_qty", sa.Float, nullable=True),
            sa.Column("safety_stock", sa.Float, nullable=True),
            sa.Column("unit_cost", sa.Float, nullable=True),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "item_code",
                name="uq_canonical_items_code",
            ),
        )
        op.create_index(
            "idx_canonical_items_config",
            "canonical_items",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_nodes"):
        op.create_table(
            "canonical_nodes",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("node_code", sa.Text, nullable=False),
            sa.Column("node_name", sa.Text, nullable=True),
            sa.Column("node_type", sa.Text, nullable=False),
            sa.Column("timezone", sa.Text, nullable=True),
            sa.Column("region", sa.Text, nullable=True),
            sa.Column("service_level", sa.Float, nullable=True),
            sa.Column("lead_time_days", sa.Integer, nullable=False, server_default="0"),
            sa.Column("storage_capacity", sa.Float, nullable=True),
            sa.Column(
                "allow_storage_over_capacity",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("storage_cost_fixed", sa.Float, nullable=True),
            sa.Column("storage_over_capacity_fixed_cost", sa.Float, nullable=True),
            sa.Column("storage_over_capacity_variable_cost", sa.Float, nullable=True),
            sa.Column("review_period_days", sa.Integer, nullable=True),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "node_code",
                name="uq_canonical_nodes_code",
            ),
        )
        op.create_index(
            "idx_canonical_nodes_config",
            "canonical_nodes",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_node_items"):
        op.create_table(
            "canonical_node_items",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("node_code", sa.Text, nullable=False),
            sa.Column("item_code", sa.Text, nullable=False),
            sa.Column(
                "initial_inventory", sa.Float, nullable=False, server_default="0"
            ),
            sa.Column("reorder_point", sa.Float, nullable=True),
            sa.Column("order_up_to", sa.Float, nullable=True),
            sa.Column("min_order_qty", sa.Float, nullable=True),
            sa.Column("order_multiple", sa.Float, nullable=True),
            sa.Column("safety_stock", sa.Float, nullable=True),
            sa.Column("storage_cost", sa.Float, nullable=True),
            sa.Column("stockout_cost", sa.Float, nullable=True),
            sa.Column("backorder_cost", sa.Float, nullable=True),
            sa.Column("lead_time_days", sa.Integer, nullable=True),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "node_code",
                "item_code",
                name="uq_canonical_node_items",
            ),
        )
        op.create_index(
            "idx_canonical_node_items_config",
            "canonical_node_items",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_node_production"):
        op.create_table(
            "canonical_node_production",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("node_code", sa.Text, nullable=False),
            sa.Column("item_code", sa.Text, nullable=True),
            sa.Column("production_capacity", sa.Float, nullable=True),
            sa.Column(
                "allow_over_capacity",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("over_capacity_fixed_cost", sa.Float, nullable=True),
            sa.Column("over_capacity_variable_cost", sa.Float, nullable=True),
            sa.Column("production_cost_fixed", sa.Float, nullable=True),
            sa.Column("production_cost_variable", sa.Float, nullable=True),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "node_code",
                "item_code",
                name="uq_canonical_node_production",
            ),
        )
        op.create_index(
            "idx_canonical_node_production_config",
            "canonical_node_production",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_arcs"):
        op.create_table(
            "canonical_arcs",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("from_node", sa.Text, nullable=False),
            sa.Column("to_node", sa.Text, nullable=False),
            sa.Column("arc_type", sa.Text, nullable=False, server_default="transport"),
            sa.Column("lead_time_days", sa.Integer, nullable=False, server_default="0"),
            sa.Column("capacity_per_day", sa.Float, nullable=True),
            sa.Column(
                "allow_over_capacity",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("transportation_cost_fixed", sa.Float, nullable=True),
            sa.Column("transportation_cost_variable", sa.Float, nullable=True),
            sa.Column("min_order_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column(
                "order_multiple_json", sa.Text, nullable=False, server_default="{}"
            ),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "from_node",
                "to_node",
                "arc_type",
                name="uq_canonical_arcs_pair",
            ),
        )
        op.create_index(
            "idx_canonical_arcs_config",
            "canonical_arcs",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_boms"):
        op.create_table(
            "canonical_boms",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("parent_item", sa.Text, nullable=False),
            sa.Column("child_item", sa.Text, nullable=False),
            sa.Column("quantity", sa.Float, nullable=False),
            sa.Column("scrap_rate", sa.Float, nullable=True),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "parent_item",
                "child_item",
                name="uq_canonical_boms_pair",
            ),
        )
        op.create_index(
            "idx_canonical_boms_config",
            "canonical_boms",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_demands"):
        op.create_table(
            "canonical_demands",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("node_code", sa.Text, nullable=False),
            sa.Column("item_code", sa.Text, nullable=False),
            sa.Column("bucket", sa.Text, nullable=False),
            sa.Column("demand_model", sa.Text, nullable=False, server_default="normal"),
            sa.Column("mean", sa.Float, nullable=False, server_default="0"),
            sa.Column("std_dev", sa.Float, nullable=True),
            sa.Column("min_qty", sa.Float, nullable=True),
            sa.Column("max_qty", sa.Float, nullable=True),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "node_code",
                "item_code",
                "bucket",
                name="uq_canonical_demands_bucket",
            ),
        )
        op.create_index(
            "idx_canonical_demands_config",
            "canonical_demands",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_capacities"):
        op.create_table(
            "canonical_capacities",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("resource_code", sa.Text, nullable=False),
            sa.Column("resource_type", sa.Text, nullable=False, server_default="node"),
            sa.Column("bucket", sa.Text, nullable=False),
            sa.Column("capacity", sa.Float, nullable=False),
            sa.Column("calendar_code", sa.Text, nullable=True),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "resource_code",
                "resource_type",
                "bucket",
                name="uq_canonical_capacities_bucket",
            ),
        )
        op.create_index(
            "idx_canonical_capacities_config",
            "canonical_capacities",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_hierarchies"):
        op.create_table(
            "canonical_hierarchies",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("hierarchy_type", sa.Text, nullable=False),
            sa.Column("node_key", sa.Text, nullable=False),
            sa.Column("parent_key", sa.Text, nullable=True),
            sa.Column("level", sa.Text, nullable=True),
            sa.Column("sort_order", sa.Integer, nullable=True),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "hierarchy_type",
                "node_key",
                name="uq_canonical_hierarchies_key",
            ),
        )
        op.create_index(
            "idx_canonical_hierarchies_config",
            "canonical_hierarchies",
            ["config_version_id"],
            unique=False,
        )

    if not insp.has_table("canonical_calendars"):
        op.create_table(
            "canonical_calendars",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "config_version_id",
                sa.Integer,
                sa.ForeignKey("canonical_config_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("calendar_code", sa.Text, nullable=False),
            sa.Column("timezone", sa.Text, nullable=True),
            sa.Column("definition_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("attributes_json", sa.Text, nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "config_version_id",
                "calendar_code",
                name="uq_canonical_calendars_code",
            ),
        )
        op.create_index(
            "idx_canonical_calendars_config",
            "canonical_calendars",
            ["config_version_id"],
            unique=False,
        )

    if insp.has_table("plan_versions"):
        cols = {col["name"] for col in insp.get_columns("plan_versions")}
        if "config_version_id" not in cols:
            op.add_column(
                "plan_versions",
                sa.Column("config_version_id", sa.Integer, nullable=True),
            )
    if insp.has_table("runs"):
        cols = {col["name"] for col in insp.get_columns("runs")}
        if "config_version_id" not in cols:
            op.add_column(
                "runs",
                sa.Column("config_version_id", sa.Integer, nullable=True),
            )
        existing_idx = {ix["name"] for ix in insp.get_indexes("runs")}
        if "idx_runs_config_version" not in existing_idx:
            op.create_index(
                "idx_runs_config_version", "runs", ["config_version_id"], unique=False
            )


def downgrade() -> None:
    op.drop_index("idx_canonical_calendars_config", table_name="canonical_calendars")
    op.drop_table("canonical_calendars")

    op.drop_index(
        "idx_canonical_hierarchies_config", table_name="canonical_hierarchies"
    )
    op.drop_table("canonical_hierarchies")

    op.drop_index("idx_canonical_capacities_config", table_name="canonical_capacities")
    op.drop_table("canonical_capacities")

    op.drop_index("idx_canonical_demands_config", table_name="canonical_demands")
    op.drop_table("canonical_demands")

    op.drop_index("idx_canonical_boms_config", table_name="canonical_boms")
    op.drop_table("canonical_boms")

    op.drop_index("idx_canonical_arcs_config", table_name="canonical_arcs")
    op.drop_table("canonical_arcs")

    op.drop_index(
        "idx_canonical_node_production_config", table_name="canonical_node_production"
    )
    op.drop_table("canonical_node_production")

    op.drop_index("idx_canonical_node_items_config", table_name="canonical_node_items")
    op.drop_table("canonical_node_items")

    op.drop_index("idx_canonical_nodes_config", table_name="canonical_nodes")
    op.drop_table("canonical_nodes")

    op.drop_index("idx_canonical_items_config", table_name="canonical_items")
    op.drop_table("canonical_items")

    op.drop_table("canonical_config_versions")

    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table("runs"):
        cols = {col["name"] for col in insp.get_columns("runs")}
        if "config_version_id" in cols:
            with op.batch_alter_table("runs") as batch:
                batch.drop_column("config_version_id")
        existing_idx = {ix["name"] for ix in insp.get_indexes("runs")}
        if "idx_runs_config_version" in existing_idx:
            op.drop_index("idx_runs_config_version", table_name="runs")
    if insp.has_table("plan_versions"):
        cols = {col["name"] for col in insp.get_columns("plan_versions")}
        if "config_version_id" in cols:
            with op.batch_alter_table("plan_versions") as batch:
                batch.drop_column("config_version_id")
