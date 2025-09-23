"""add plan versions and artifacts"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7218ec6eb99'
down_revision = '0004_canonical_config'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_versions",
        sa.Column("version_id", sa.Text, primary_key=True),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("base_scenario_id", sa.Integer, nullable=True),
        sa.Column("status", sa.Text, nullable=True),
        sa.Column("cutover_date", sa.Text, nullable=True),
        sa.Column("recon_window_days", sa.Integer, nullable=True),
        sa.Column("objective", sa.Text, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("config_version_id", sa.Integer, nullable=True),
    )
    op.create_table(
        "plan_artifacts",
        sa.Column("version_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("json_text", sa.Text, nullable=False),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("version_id", "name"),
    )
    op.create_index(
        "idx_plan_artifacts_version", "plan_artifacts", ["version_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_plan_artifacts_version", table_name="plan_artifacts")
    op.drop_table("plan_artifacts")
    op.drop_table("plan_versions")