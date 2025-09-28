"""add plan_version_id to runs table

Revision ID: 0afb1234
Revises: e759344
Create Date: 2025-09-26 12:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "0afb1234plan"
down_revision = "b7218ec6eb99"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("plan_version_id", sa.String(), nullable=True))
        batch_op.create_index("ix_runs_plan_version_id", ["plan_version_id"])


def downgrade():
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_index("ix_runs_plan_version_id")
        batch_op.drop_column("plan_version_id")
