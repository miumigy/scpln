"""add_input_set_approval_columns"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1d7b0dcf4c23"
down_revision = "8eeb7b69d3b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "planning_input_sets",
        sa.Column("approved_by", sa.String(255), nullable=True),
    )
    op.add_column(
        "planning_input_sets",
        sa.Column("approved_at", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "planning_input_sets",
        sa.Column("review_comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("planning_input_sets", "review_comment")
    op.drop_column("planning_input_sets", "approved_at")
    op.drop_column("planning_input_sets", "approved_by")
