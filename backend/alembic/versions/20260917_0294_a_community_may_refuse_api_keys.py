"""A community may decline personal API keys.

One column on ``public.guilds``: whether a personal API key may be used against
this guild. True for every existing row, which is what they do today.

It lives here rather than on ``guild_auth_policies`` for the reason ``status``
does: the guild-access gate already holds the guild row, and the answer has to
outlive the policy row, which is deleted when a guild lifts its sign-in
requirement.

Nothing is backfilled — the server default fills the existing rows as the
column is added — so there is no DML to order against the table's RLS.

Revision ID: 20260917_0294
Revises: 20260917_0293
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0294"
down_revision = "20260917_0293"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column(
            "allow_api_keys",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("guilds", "allow_api_keys", schema="public")
