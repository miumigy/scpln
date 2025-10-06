"""add plan db tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "e2ed745f51a9"
down_revision = "0afb1234plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not insp.has_table("plan_series"):
        op.create_table(
            "plan_series",
            sa.Column("version_id", sa.Text, nullable=False),
            sa.Column("level", sa.Text, nullable=False),
            sa.Column("time_bucket_type", sa.Text, nullable=False),
            sa.Column("time_bucket_key", sa.Text, nullable=False),
            sa.Column("item_key", sa.Text, nullable=False),
            sa.Column("item_name", sa.Text, nullable=True),
            sa.Column("location_key", sa.Text, nullable=False),
            sa.Column("location_type", sa.Text, nullable=True),
            sa.Column("region_key", sa.Text, nullable=True),
            sa.Column("network_key", sa.Text, nullable=True),
            sa.Column("scenario_id", sa.Integer, nullable=True),
            sa.Column("config_version_id", sa.Integer, nullable=True),
            sa.Column("source", sa.Text, nullable=True),
            sa.Column("policy", sa.Text, nullable=True),
            sa.Column(
                "cutover_flag",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("boundary_zone", sa.Text, nullable=True),
            sa.Column("window_index", sa.Integer, nullable=True),
            sa.Column(
                "lock_flag",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("locked_by", sa.Text, nullable=True),
            sa.Column("quality_flag", sa.Text, nullable=True),
            sa.Column("source_run_id", sa.Text, nullable=True),
            sa.Column(
                "demand",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "supply",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "backlog",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "inventory_open",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "inventory_close",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "prod_qty",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "ship_qty",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "capacity_used",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "cost_total",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column("service_level", sa.Float, nullable=True),
            sa.Column("spill_in", sa.Float, nullable=True),
            sa.Column("spill_out", sa.Float, nullable=True),
            sa.Column("adjustment", sa.Float, nullable=True),
            sa.Column("carryover_in", sa.Float, nullable=True),
            sa.Column("carryover_out", sa.Float, nullable=True),
            sa.Column("extra_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Integer, nullable=False),
            sa.PrimaryKeyConstraint(
                "version_id",
                "level",
                "time_bucket_type",
                "time_bucket_key",
                "item_key",
                "location_key",
            ),
            sa.ForeignKeyConstraint(
                ["version_id"],
                ["plan_versions.version_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["config_version_id"],
                ["canonical_config_versions.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["scenario_id"],
                ["scenarios.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["source_run_id"],
                ["runs.run_id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "idx_plan_series_version_level_item",
            "plan_series",
            ["version_id", "level", "item_key"],
            unique=False,
        )
        op.create_index(
            "idx_plan_series_version_level_bucket",
            "plan_series",
            ["version_id", "level", "time_bucket_type", "time_bucket_key"],
            unique=False,
        )
        op.create_index(
            "idx_plan_series_level_bucket",
            "plan_series",
            ["level", "time_bucket_type", "time_bucket_key"],
            unique=False,
        )
        op.create_index(
            "idx_plan_series_version_cutover",
            "plan_series",
            ["version_id", "cutover_flag"],
            unique=False,
        )
        op.create_index(
            "idx_plan_series_source_run",
            "plan_series",
            ["source_run_id"],
            unique=False,
        )

    if not insp.has_table("plan_overrides"):
        op.create_table(
            "plan_overrides",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("version_id", sa.Text, nullable=False),
            sa.Column("level", sa.Text, nullable=False),
            sa.Column("key_hash", sa.Text, nullable=False),
            sa.Column("payload_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column(
                "lock_flag",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("locked_by", sa.Text, nullable=True),
            sa.Column("weight", sa.Float, nullable=True),
            sa.Column("author", sa.Text, nullable=True),
            sa.Column("source", sa.Text, nullable=True),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Integer, nullable=False),
            sa.ForeignKeyConstraint(
                ["version_id"],
                ["plan_versions.version_id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "version_id",
                "level",
                "key_hash",
                name="uq_plan_overrides_version_level_key",
            ),
        )
        op.create_index(
            "idx_plan_overrides_version_level",
            "plan_overrides",
            ["version_id", "level"],
            unique=False,
        )
        op.create_index(
            "idx_plan_overrides_version_lock",
            "plan_overrides",
            ["version_id", "lock_flag"],
            unique=False,
        )

    if not insp.has_table("plan_override_events"):
        op.create_table(
            "plan_override_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("override_id", sa.Integer, nullable=False),
            sa.Column("version_id", sa.Text, nullable=False),
            sa.Column("level", sa.Text, nullable=False),
            sa.Column("key_hash", sa.Text, nullable=False),
            sa.Column("event_type", sa.Text, nullable=False),
            sa.Column("event_ts", sa.Integer, nullable=False),
            sa.Column("payload_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("actor", sa.Text, nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.ForeignKeyConstraint(
                ["override_id"],
                ["plan_overrides.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["version_id"],
                ["plan_versions.version_id"],
                ondelete="CASCADE",
            ),
        )
        op.create_index(
            "idx_plan_override_events_version_ts",
            "plan_override_events",
            ["version_id", "event_ts"],
            unique=False,
        )
        op.create_index(
            "idx_plan_override_events_override_ts",
            "plan_override_events",
            ["override_id", "event_ts"],
            unique=False,
        )

    if not insp.has_table("plan_kpis"):
        op.create_table(
            "plan_kpis",
            sa.Column("version_id", sa.Text, nullable=False),
            sa.Column("metric", sa.Text, nullable=False),
            sa.Column("bucket_type", sa.Text, nullable=False, server_default="total"),
            sa.Column("bucket_key", sa.Text, nullable=False, server_default="total"),
            sa.Column(
                "value",
                sa.Float,
                nullable=False,
                server_default="0",
            ),
            sa.Column("unit", sa.Text, nullable=True),
            sa.Column("source", sa.Text, nullable=True),
            sa.Column("source_run_id", sa.Text, nullable=True),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Integer, nullable=False),
            sa.PrimaryKeyConstraint(
                "version_id",
                "metric",
                "bucket_type",
                "bucket_key",
            ),
            sa.ForeignKeyConstraint(
                ["version_id"],
                ["plan_versions.version_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["source_run_id"],
                ["runs.run_id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "idx_plan_kpis_metric_bucket",
            "plan_kpis",
            ["metric", "bucket_type", "bucket_key"],
            unique=False,
        )
        op.create_index(
            "idx_plan_kpis_version_bucket",
            "plan_kpis",
            ["version_id", "bucket_type"],
            unique=False,
        )
        op.create_index(
            "idx_plan_kpis_source_run",
            "plan_kpis",
            ["source_run_id"],
            unique=False,
        )

    if not insp.has_table("plan_jobs"):
        op.create_table(
            "plan_jobs",
            sa.Column("job_id", sa.Text, primary_key=True),
            sa.Column("version_id", sa.Text, nullable=False),
            sa.Column("config_version_id", sa.Integer, nullable=True),
            sa.Column("scenario_id", sa.Integer, nullable=True),
            sa.Column("status", sa.Text, nullable=False),
            sa.Column("run_id", sa.Text, nullable=True),
            sa.Column("trigger", sa.Text, nullable=True),
            sa.Column("submitted_at", sa.Integer, nullable=False),
            sa.Column("started_at", sa.Integer, nullable=True),
            sa.Column("finished_at", sa.Integer, nullable=True),
            sa.Column("duration_ms", sa.Integer, nullable=True),
            sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("payload_json", sa.Text, nullable=True),
            sa.ForeignKeyConstraint(
                ["job_id"],
                ["jobs.job_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["version_id"],
                ["plan_versions.version_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["config_version_id"],
                ["canonical_config_versions.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["scenario_id"],
                ["scenarios.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["run_id"],
                ["runs.run_id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "idx_plan_jobs_version",
            "plan_jobs",
            ["version_id"],
            unique=False,
        )
        op.create_index(
            "idx_plan_jobs_config_version",
            "plan_jobs",
            ["config_version_id"],
            unique=False,
        )
        op.create_index(
            "idx_plan_jobs_run",
            "plan_jobs",
            ["run_id"],
            unique=False,
        )
        op.create_index(
            "idx_plan_jobs_status_submitted",
            "plan_jobs",
            ["status", "submitted_at"],
            unique=False,
        )
        op.create_index(
            "idx_plan_jobs_trigger_submitted",
            "plan_jobs",
            ["trigger", "submitted_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if insp.has_table("plan_jobs"):
        existing_idx = {ix["name"] for ix in insp.get_indexes("plan_jobs")}
        if "idx_plan_jobs_trigger_submitted" in existing_idx:
            op.drop_index("idx_plan_jobs_trigger_submitted", table_name="plan_jobs")
        if "idx_plan_jobs_status_submitted" in existing_idx:
            op.drop_index("idx_plan_jobs_status_submitted", table_name="plan_jobs")
        if "idx_plan_jobs_run" in existing_idx:
            op.drop_index("idx_plan_jobs_run", table_name="plan_jobs")
        if "idx_plan_jobs_config_version" in existing_idx:
            op.drop_index("idx_plan_jobs_config_version", table_name="plan_jobs")
        if "idx_plan_jobs_version" in existing_idx:
            op.drop_index("idx_plan_jobs_version", table_name="plan_jobs")
        op.drop_table("plan_jobs")

    if insp.has_table("plan_kpis"):
        existing_idx = {ix["name"] for ix in insp.get_indexes("plan_kpis")}
        if "idx_plan_kpis_source_run" in existing_idx:
            op.drop_index("idx_plan_kpis_source_run", table_name="plan_kpis")
        if "idx_plan_kpis_version_bucket" in existing_idx:
            op.drop_index("idx_plan_kpis_version_bucket", table_name="plan_kpis")
        if "idx_plan_kpis_metric_bucket" in existing_idx:
            op.drop_index("idx_plan_kpis_metric_bucket", table_name="plan_kpis")
        op.drop_table("plan_kpis")

    if insp.has_table("plan_override_events"):
        existing_idx = {ix["name"] for ix in insp.get_indexes("plan_override_events")}
        if "idx_plan_override_events_override_ts" in existing_idx:
            op.drop_index(
                "idx_plan_override_events_override_ts",
                table_name="plan_override_events",
            )
        if "idx_plan_override_events_version_ts" in existing_idx:
            op.drop_index(
                "idx_plan_override_events_version_ts",
                table_name="plan_override_events",
            )
        op.drop_table("plan_override_events")

    if insp.has_table("plan_overrides"):
        existing_idx = {ix["name"] for ix in insp.get_indexes("plan_overrides")}
        if "idx_plan_overrides_version_lock" in existing_idx:
            op.drop_index(
                "idx_plan_overrides_version_lock", table_name="plan_overrides"
            )
        if "idx_plan_overrides_version_level" in existing_idx:
            op.drop_index(
                "idx_plan_overrides_version_level", table_name="plan_overrides"
            )
        op.drop_table("plan_overrides")

    if insp.has_table("plan_series"):
        existing_idx = {ix["name"] for ix in insp.get_indexes("plan_series")}
        if "idx_plan_series_source_run" in existing_idx:
            op.drop_index("idx_plan_series_source_run", table_name="plan_series")
        if "idx_plan_series_version_cutover" in existing_idx:
            op.drop_index("idx_plan_series_version_cutover", table_name="plan_series")
        if "idx_plan_series_level_bucket" in existing_idx:
            op.drop_index("idx_plan_series_level_bucket", table_name="plan_series")
        if "idx_plan_series_version_level_bucket" in existing_idx:
            op.drop_index(
                "idx_plan_series_version_level_bucket",
                table_name="plan_series",
            )
        if "idx_plan_series_version_level_item" in existing_idx:
            op.drop_index(
                "idx_plan_series_version_level_item",
                table_name="plan_series",
            )
        op.drop_table("plan_series")
