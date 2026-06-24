"""Scope user API keys: read_only + guild-bound least-privilege PATs.

Adds two columns to ``user_api_keys`` so a personal access token (e.g. one
embedded in an MCP server config) can be minted least-privilege:

  * ``read_only`` — the auth dependency refuses any unsafe HTTP method for the key.
  * ``guild_id``  — the key is pinned to a single guild (enforced against the
    ``/g/{guild_id}`` path). FK ON DELETE CASCADE so a deleted guild removes its
    scoped keys rather than leaving a dangling binding.

Existing keys keep today's full-access behavior (``read_only=false``,
``guild_id=NULL``). See ``history/mcp-server-design.md``.

Revision ID: 20260623_0121
Revises: 20260622_0120
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260623_0121"
down_revision = "20260622_0120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_api_keys",
        sa.Column(
            "read_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "user_api_keys",
        sa.Column("guild_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_user_api_keys_guild_id", "user_api_keys", ["guild_id"])
    op.create_foreign_key(
        "fk_user_api_keys_guild_id_guilds",
        "user_api_keys",
        "guilds",
        ["guild_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Drop the server_default now that existing rows are backfilled; the ORM
    # supplies the value on insert.
    op.alter_column("user_api_keys", "read_only", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "fk_user_api_keys_guild_id_guilds", "user_api_keys", type_="foreignkey"
    )
    op.drop_index("ix_user_api_keys_guild_id", table_name="user_api_keys")
    op.drop_column("user_api_keys", "guild_id")
    op.drop_column("user_api_keys", "read_only")
