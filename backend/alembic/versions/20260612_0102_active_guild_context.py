"""Server-held guild context: users.active_guild_id.

Adds the single nullable column that replaces the per-request guild
context protocol entirely: ``users.active_guild_id`` records which guild
the user is currently in, and ``NULL`` means personal (cross-guild) mode.
It is set by ``PUT /users/me/guild-context`` when the user clicks a guild
or the personal page, and read by the request dependencies on every call
— no per-request guild context travels with requests anymore.

``ON DELETE SET NULL`` makes guild deletion self-healing: members of a
deleted guild drop to personal mode automatically. No backfill — everyone
starts in personal mode and their first guild click sets the flag.

``users`` is a shared (public-schema) table, so this is a normal Alembic
migration with no per-guild-schema work.

Revision ID: 20260612_0102
Revises: 20260611_0101
Create Date: 2026-06-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260612_0102"
down_revision = "20260611_0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("active_guild_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_active_guild_id_guilds",
        "users",
        "guilds",
        ["active_guild_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_active_guild_id_guilds", "users", type_="foreignkey")
    op.drop_column("users", "active_guild_id")
