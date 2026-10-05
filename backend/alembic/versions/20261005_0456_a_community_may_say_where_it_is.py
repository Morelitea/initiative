"""A community may say where it is

``guilds.location`` holds where a community is — a country at least, and as
much finer as its admin cares to give — or NULL for one that has not said.

0138 pinned the guild-admin write path on ``public.guilds`` to a literal column
list, so the new column names itself in a column grant, as 0196 and 0200 did
for theirs. A community's own admin sets it, from Settings -> Community.

Revision ID: 20261005_0456
Revises: 20261004_0455
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261005_0456"
down_revision = "20261004_0455"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column("location", postgresql.JSONB(), nullable=True),
    )
    op.execute("GRANT UPDATE (location) ON TABLE public.guilds TO app_guild_base")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (location) ON TABLE public.guilds FROM app_guild_base")
    op.drop_column("guilds", "location")
