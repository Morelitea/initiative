"""add task created_by_id

Revision ID: 20260217_0054
Revises: 20260216_0053
Create Date: 2026-02-17
"""

revision = '20260217_0054'
down_revision = '20260216_0053'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column('tasks', sa.Column('created_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_tasks_created_by_id',
        'tasks',
        'users',
        ['created_by_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_tasks_created_by_id', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'created_by_id')
