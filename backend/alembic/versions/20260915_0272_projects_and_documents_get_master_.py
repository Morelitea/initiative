"""Projects and documents get master switches.

Every tool now carries a ``{plural}_enabled`` master switch on the initiative.
Projects and documents were the two exceptions — always on, with no column at
all — because they were the only places content could live and the other tools
hung off them. Relationships ended that: anything links to anything, so an
initiative that is only a calendar is a coherent thing to want.

Both columns default to TRUE, which is what makes this a widening rather than a
change. Every initiative that already exists keeps projects and documents, and
one created without an opinion still gets them; the switch is simply there to
turn off now.

``initiatives`` is a structural table — guild-level, guarded by the schema
boundary rather than initiative-member RLS — so there is no FORCE to lift and
nothing to backfill beyond the server default.
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260915_0272"
down_revision = "20260915_0271"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    # Autogenerate also proposed dropping the ``search:<digest>`` comment on
    # search_entries. That stamp is the search reindex generation, written by
    # provisioning rather than by any migration, and this change touches no
    # search source — so it is not ours to clear.
    with op.batch_alter_table("initiatives", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "projects_enabled",
                sa.Boolean(),
                server_default="true",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "documents_enabled",
                sa.Boolean(),
                server_default="true",
                nullable=False,
            )
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("initiatives", schema=None) as batch_op:
        batch_op.drop_column("documents_enabled")
        batch_op.drop_column("projects_enabled")
