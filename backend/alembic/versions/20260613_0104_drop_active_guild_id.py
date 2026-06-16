"""Drop users.active_guild_id

Guild context is now resolved per-request from the ``/g/{guild_id}`` URL path
(path-based tenancy) — every tab carries its own guild in the URL. The
server-held ``active_guild_id`` flag is no longer read or written by any handler,
so the column is removed along with its FK to ``guilds``.

Revision ID: 20260613_0104
Revises: 20260613_0103
Create Date: 2026-06-13
"""

import sqlalchemy as sa
from alembic import op

revision = "20260613_0104"
down_revision = "20260613_0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dropping the column drops its FK constraint to guilds automatically.
    op.drop_column("users", "active_guild_id")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("active_guild_id", sa.Integer(), nullable=True),
    )
    # Re-create the FK under the SAME name the original migration used
    # (fk_users_active_guild_id_guilds), so a full down-migration can drop it
    # cleanly when it reaches 20260612_0102's downgrade.
    op.create_foreign_key(
        "fk_users_active_guild_id_guilds",
        "users",
        "guilds",
        ["active_guild_id"],
        ["id"],
        ondelete="SET NULL",
    )
