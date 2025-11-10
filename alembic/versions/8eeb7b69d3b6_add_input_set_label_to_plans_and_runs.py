"""add_input_set_label_to_plans_and_runs"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8eeb7b69d3b6"
down_revision = "36858d371b14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_versions",
        sa.Column("input_set_label", sa.String(255), nullable=True),
    )
    op.create_index(
        op.f("ix_plan_versions_input_set_label"),
        "plan_versions",
        ["input_set_label"],
        unique=False,
    )
    op.add_column("runs", sa.Column("input_set_label", sa.String(255), nullable=True))
    op.create_index(
        op.f("ix_runs_input_set_label"), "runs", ["input_set_label"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_runs_input_set_label"), table_name="runs")
    op.drop_column("runs", "input_set_label")
    op.drop_index(op.f("ix_plan_versions_input_set_label"), table_name="plan_versions")
    op.drop_column("plan_versions", "input_set_label")
