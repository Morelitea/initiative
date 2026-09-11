"""a webhook subscription records the install that registered it

An envelope names the guild it came from and the member whose write caused it.
Both were row ids. They become references, and which references depends on who
is receiving: an app already holds a name for the guild and for each member,
minted at its install, and a delivery should arrive under those rather than
introduce a second set the app cannot match to anything it has stored.

So the subscription has to remember whether an app registered it. Guild
content, so this walks ``guild_template`` and every ``guild_<id>``.

Conditional DDL, so a schema that already carries the column converges
rather than failing. Existing rows stay NULL. Nothing recorded the delegate at the time, and the
target URL is not evidence of one — a subscription that predates this is named
in its own sector until it is registered again.

Revision ID: 20260911_0254
Revises: 20260910_0253
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260911_0254"
down_revision = "20260910_0253"
branch_labels = None
depends_on = None


def _route(connection, schema: str) -> None:
    connection.execute(
        sa.text("SELECT set_config('search_path', :sp, true)"),
        {"sp": f'"{schema}", public'},
    )


def upgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        _route(connection, schema)
        op.execute(
            "ALTER TABLE webhook_subscriptions "
            "ADD COLUMN IF NOT EXISTS app_install_id integer"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_webhook_subscriptions_app_install_id "
            "ON webhook_subscriptions (app_install_id)"
        )


def downgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        _route(connection, schema)
        op.execute("DROP INDEX IF EXISTS ix_webhook_subscriptions_app_install_id")
        op.execute(
            "ALTER TABLE webhook_subscriptions DROP COLUMN IF EXISTS app_install_id"
        )
