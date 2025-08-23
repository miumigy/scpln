from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not insp.has_table("configs"):
        op.create_table(
            "configs",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("json_text", sa.Text, nullable=False),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Integer, nullable=False),
        )

    if not insp.has_table("runs"):
        op.create_table(
            "runs",
            sa.Column("run_id", sa.Text, primary_key=True),
            sa.Column("started_at", sa.Integer, nullable=False),
            sa.Column("duration_ms", sa.Integer, nullable=False),
            sa.Column("schema_version", sa.Text, nullable=False),
            sa.Column("summary", sa.Text, nullable=False),
            sa.Column("results", sa.Text, nullable=False),
            sa.Column("daily_profit_loss", sa.Text, nullable=False),
            sa.Column("cost_trace", sa.Text, nullable=False),
            sa.Column("config_id", sa.Integer, nullable=True),
            sa.Column("config_json", sa.Text, nullable=True),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Integer, nullable=False),
        )
    # indexes for runs
    if insp.has_table("runs"):
        existing_idx = {ix["name"] for ix in insp.get_indexes("runs")}
        if "idx_runs_started_at" not in existing_idx:
            op.create_index("idx_runs_started_at", "runs", ["started_at"], unique=False)
        if "idx_runs_schema_version" not in existing_idx:
            op.create_index(
                "idx_runs_schema_version", "runs", ["schema_version"], unique=False
            )
        if "idx_runs_config_id" not in existing_idx:
            op.create_index("idx_runs_config_id", "runs", ["config_id"], unique=False)

    if not insp.has_table("jobs"):
        op.create_table(
            "jobs",
            sa.Column("job_id", sa.Text, primary_key=True),
            sa.Column("type", sa.Text, nullable=False),
            sa.Column("status", sa.Text, nullable=False),
            sa.Column("submitted_at", sa.Integer, nullable=False),
            sa.Column("started_at", sa.Integer, nullable=True),
            sa.Column("finished_at", sa.Integer, nullable=True),
            sa.Column("params_json", sa.Text, nullable=True),
            sa.Column("run_id", sa.Text, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("result_json", sa.Text, nullable=True),
        )
    if insp.has_table("jobs"):
        existing_idx = {ix["name"] for ix in insp.get_indexes("jobs")}
        if "idx_jobs_status_submitted" not in existing_idx:
            op.create_index(
                "idx_jobs_status_submitted",
                "jobs",
                ["status", "submitted_at"],
                unique=False,
            )

    if not insp.has_table("product_hierarchy"):
        op.create_table(
            "product_hierarchy",
            sa.Column("key", sa.Text, primary_key=True),
            sa.Column("item", sa.Text, nullable=True),
            sa.Column("category", sa.Text, nullable=True),
            sa.Column("department", sa.Text, nullable=True),
        )

    if not insp.has_table("location_hierarchy"):
        op.create_table(
            "location_hierarchy",
            sa.Column("key", sa.Text, primary_key=True),
            sa.Column("region", sa.Text, nullable=True),
            sa.Column("country", sa.Text, nullable=True),
        )


def downgrade() -> None:
    op.drop_table("location_hierarchy")
    op.drop_table("product_hierarchy")
    op.drop_index("idx_jobs_status_submitted", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("idx_runs_config_id", table_name="runs")
    op.drop_index("idx_runs_schema_version", table_name="runs")
    op.drop_index("idx_runs_started_at", table_name="runs")
    op.drop_table("runs")
    op.drop_table("configs")
