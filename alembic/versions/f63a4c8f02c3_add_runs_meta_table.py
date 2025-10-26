"""add runs_meta table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f63a4c8f02c3"
down_revision = "7749869ca939"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs_meta",
        sa.Column("run_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("approved_at", sa.BigInteger(), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column(
            "baseline",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("idx_runs_meta_baseline", "runs_meta", ["baseline"])
    op.create_index("idx_runs_meta_archived", "runs_meta", ["archived"])


def downgrade() -> None:
    op.drop_index("idx_runs_meta_archived", table_name="runs_meta")
    op.drop_index("idx_runs_meta_baseline", table_name="runs_meta")
    op.drop_table("runs_meta")
