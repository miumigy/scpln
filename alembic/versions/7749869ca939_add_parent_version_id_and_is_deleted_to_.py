"""add parent_version_id and is_deleted to canonical_config_versions"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7749869ca939"
down_revision = "4eab49599376"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "canonical_config_versions",
        sa.Column("parent_version_id", sa.Integer, nullable=True),
    )
    op.add_column(
        "canonical_config_versions",
        sa.Column(
            "is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")
        ),
    )


def downgrade() -> None:
    op.drop_column("canonical_config_versions", "is_deleted")
    op.drop_column("canonical_config_versions", "parent_version_id")
