"""pictures and notices name no author

``guild_images``, ``announcements`` and ``announcement_images`` each carried a
``created_by`` pointing at ``users``. None of them was read for anything: a
community's pictures are the community's, and a notice or its screenshots are
the deployment's. The columns go, and with them the one foreign key without a
delete rule, on ``guild_images``, that stopped an account from being removed.

Revision ID: 20260924_0373
Revises: 20260923_0372
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0373"
down_revision = "20260923_0372"
branch_labels = None
depends_on = None


# (table, delete rule the key had)
_TABLES = (
    ("guild_images", None),
    ("announcements", "SET NULL"),
    ("announcement_images", "SET NULL"),
)


def upgrade() -> None:
    for table, _ in _TABLES:
        op.drop_column(table, "created_by", schema="public")


def downgrade() -> None:
    for table, ondelete in _TABLES:
        op.add_column(
            table,
            sa.Column("created_by", sa.Integer(), nullable=True),
            schema="public",
        )
        op.create_foreign_key(
            f"{table}_created_by_fkey",
            table,
            "users",
            ["created_by"],
            ["id"],
            source_schema="public",
            referent_schema="public",
            ondelete=ondelete,
        )
