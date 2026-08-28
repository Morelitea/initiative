"""hold the handle a guild-wide vendor flow writes back against

Some vendors do not authorize an organization by anything an admin can type.
GitHub, Slack and Linear all put the organization-wide install behind a page of
their own, where somebody who owns the account chooses what the app may see —
and what comes back is an installation, not a name. Until now the only way to
join that to a guild was an admin retyping the organization's login into a text
box and hoping it matched whatever somebody had installed.

A ``static`` connection may now declare a ``connect_path``, which makes it a
flow a guild admin runs once for everybody. This column is what the two ends are
joined by: an opaque handle minted when the admin starts, carried to the app in
the browser, and named again when the app writes the result back over its own
authenticated channel. A write-back naming a handle this column never held is
refused — which is what keeps somebody who merely knows a guild id from binding
their own organization to that guild.

Keyed by connection id, because an app may declare more than one. Empty for
every install that exists today, and for every app that has no such flow.

Revision ID: 20260828_0198
Revises: 20260827_0197
Create Date: 2026-08-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260828_0198"
down_revision = "20260827_0197"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("guild_apps", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "connection_refs",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="{}",
                nullable=False,
            )
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("guild_apps", schema=None) as batch_op:
        batch_op.drop_column("connection_refs")
