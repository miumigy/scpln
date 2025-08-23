from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_runs_scenario_id"
down_revision = "0002_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table("runs"):
        cols = {c["name"] for c in insp.get_columns("runs")}
        if "scenario_id" not in cols:
            op.add_column("runs", sa.Column("scenario_id", sa.Integer, nullable=True))
        existing_idx = {ix["name"] for ix in insp.get_indexes("runs")}
        if "idx_runs_scenario_id" not in existing_idx:
            op.create_index("idx_runs_scenario_id", "runs", ["scenario_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table("runs"):
        existing_idx = {ix["name"] for ix in insp.get_indexes("runs")}
        if "idx_runs_scenario_id" in existing_idx:
            op.drop_index("idx_runs_scenario_id", table_name="runs")
        cols = {c["name"] for c in insp.get_columns("runs")}
        if "scenario_id" in cols:
            op.drop_column("runs", "scenario_id")

