"""add_planning_input_set_events"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f8e8f1dd0f5"
down_revision = "1d7b0dcf4c23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planning_input_set_events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("input_set_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["input_set_id"], ["planning_input_sets.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_planning_input_set_events_input_set_id",
        "planning_input_set_events",
        ["input_set_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_planning_input_set_events_input_set_id",
        table_name="planning_input_set_events",
    )
    op.drop_table("planning_input_set_events")
