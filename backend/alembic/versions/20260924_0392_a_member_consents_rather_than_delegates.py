"""a member consents rather than delegates

``guild_app_user_delegations`` held a member's app-wide authorization for an
installed app to act as them, read by the app-signed delegation token. That
token is gone. An app acting as a member now presents a member token, issued
only against the member's answer in ``app_member_consents`` (one per purpose,
or app-wide), so the table has no reader and is dropped. Nothing is carried
over: an app asks again.

Guild content, so this walks ``guild_template`` and every ``guild_<id>``. The
downgrade recreates the table empty, with row level security on; its own-row
policies are rendered from the registry at boot like every other table's.

Revision ID: 20260924_0392
Revises: 20260924_0391
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260924_0392"
down_revision = "20260924_0391"
branch_labels = None
depends_on = None

TABLE = "guild_app_user_delegations"


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop_table)


def _drop_table() -> None:
    # Named in the schema being walked, never resolved through the search
    # path's fallback to ``public``. Its indexes, policies and grants go with
    # it.
    op.execute(
        "DO $$ BEGIN EXECUTE format("
        f"'DROP TABLE IF EXISTS %I.{TABLE}', current_schema()); END $$;"
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _create_table)


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("can_read", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("can_write", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_factor", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["app_id"], ["guild_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "app_id", "user_id", name="guild_app_user_delegations_unique_member"
        ),
    )
    op.create_index(f"ix_{TABLE}_app_id", TABLE, ["app_id"])
    op.create_index(f"ix_{TABLE}_user_id", TABLE, ["user_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
