'''"""add plan_job_id to runs table

Revision ID: 4eab49599376
Revises: e2ed745f51a9
Create Date: 2025-10-03 14:00:00

"""'''
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4eab49599376'
down_revision = 'e2ed745f51a9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plan_job_id', sa.String(), nullable=True))
        batch_op.create_index('ix_runs_plan_job_id', ['plan_job_id'], unique=False)


def downgrade():
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_index('ix_runs_plan_job_id', table_name='runs')
        batch_op.drop_column('plan_job_id')