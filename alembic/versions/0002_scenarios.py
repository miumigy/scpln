from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_scenarios"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("scenarios"):
        op.create_table(
            "scenarios",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("parent_id", sa.Integer, nullable=True),
            sa.Column("tag", sa.Text, nullable=True),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("locked", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Integer, nullable=False),
        )


def downgrade() -> None:
    op.drop_table("scenarios")
