"""Add held_at_round to queue_items for the Hold-your-turn feature.

Adds a nullable ``held_at_round`` integer column to ``queue_items``. ``NULL``
means the item is in the rotation. A non-null value is the ``current_round``
recorded when the user held this item; the rotation auto-releases held items
when the round advances past their due slot (round + 1 at the item's
position), so a held participant can't be silently forgotten.

Revision ID: 20260522_0087
Revises: 20260522_0086
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa

revision = "20260522_0087"
down_revision = "20260522_0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "queue_items",
        sa.Column("held_at_round", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("queue_items", "held_at_round")
