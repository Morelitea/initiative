"""Rename tasks.sort_order to position and widen to NUMERIC(20, 10).

Renames ``tasks.sort_order`` to ``tasks.position`` and changes its type from
DOUBLE PRECISION to NUMERIC(20, 10) so tasks can be drag-reordered with
fractional midpoint positions (sending only the moved task instead of
renumbering the whole list), mirroring counter/queue_item ``position``.

Revision ID: 20260531_0096
Revises: 20260530_0095
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa

revision = "20260531_0096"
down_revision = "20260530_0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tasks", "sort_order", new_column_name="position")
    op.alter_column(
        "tasks",
        "position",
        existing_type=sa.Float(),
        type_=sa.Numeric(20, 10),
        existing_nullable=False,
        server_default=sa.text("0"),
        postgresql_using="position::numeric(20, 10)",
    )


def downgrade() -> None:
    op.alter_column(
        "tasks",
        "position",
        existing_type=sa.Numeric(20, 10),
        type_=sa.Float(),
        existing_nullable=False,
        server_default=sa.text("'0'::double precision"),
        postgresql_using="position::double precision",
    )
    op.alter_column("tasks", "position", new_column_name="sort_order")
