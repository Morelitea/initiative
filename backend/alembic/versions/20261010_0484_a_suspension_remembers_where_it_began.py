"""a suspension remembers where it began

``guilds.status_before_suspension``: the status a suspended community had
before it was suspended, so lifting the suspension returns it there. A
moderator may suspend a deleted community, which takes it out of the purge
countdown; lifting that suspension puts it back into ``deleted``.

Revision ID: 20261010_0484
Revises: 20261010_0483
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "20261010_0484"
down_revision = "20261010_0483"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column("status_before_suspension", sa.String(length=16), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        "ck_guilds_status_before_suspension",
        "guilds",
        "status_before_suspension IS NULL OR status_before_suspension IN "
        "('active', 'read_only', 'on_hold', 'deleted')",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_guilds_status_before_suspension", "guilds", schema="public", type_="check"
    )
    op.drop_column("guilds", "status_before_suspension", schema="public")
