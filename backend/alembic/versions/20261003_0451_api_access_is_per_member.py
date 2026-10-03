"""api access is per member

Whether personal API keys reach a community moves from the community to each
of its members: ``guild_memberships.api_keys_allowed``, set by the community's
superadmin for one person at a time. ``guilds.allow_api_keys`` is dropped, and
the seat's column grant on it goes with it.

Members of a community that had switched keys off start with them off, so
nobody's access changes in the move. Every other member, and everyone who
joins later, starts with them on.

The column is added with its default before the backfill writes, and both
tables are FORCE RLS, so the backfill runs with the owner's row security lifted
on the two of them and restored after.

Revision ID: 20261003_0451
Revises: 20261003_0450
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "20261003_0451"
down_revision = "20261003_0450"
branch_labels = None
depends_on = None

TABLES = ("public.guild_memberships", "public.guilds")
SEAT_FLOOR = "app_superadmin"


def _forced(bind, table: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


def _unforced(bind, statement: str) -> None:
    """Run ``statement`` with the owner's RLS lifted on both tables, restored
    after."""
    forced = [table for table in TABLES if _forced(bind, table)]
    for table in forced:
        bind.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    try:
        bind.execute(sa.text(statement))
    finally:
        for table in forced:
            bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(
        "guild_memberships",
        sa.Column(
            "api_keys_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="public",
    )
    _unforced(
        bind,
        "UPDATE public.guild_memberships AS m SET api_keys_allowed = false"
        " FROM public.guilds AS g"
        " WHERE g.id = m.guild_id AND NOT g.allow_api_keys",
    )
    op.drop_column("guilds", "allow_api_keys", schema="public")


def downgrade() -> None:
    bind = op.get_bind()
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
    # A community whose every member had keys off goes back to refusing them;
    # any other keeps them, since one switch cannot say "some of us".
    _unforced(
        bind,
        "UPDATE public.guilds AS g SET allow_api_keys = false"
        " WHERE EXISTS (SELECT 1 FROM public.guild_memberships AS m"
        " WHERE m.guild_id = g.id)"
        " AND NOT EXISTS (SELECT 1 FROM public.guild_memberships AS m"
        " WHERE m.guild_id = g.id AND m.api_keys_allowed)",
    )
    op.drop_column("guild_memberships", "api_keys_allowed", schema="public")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SEAT_FLOOR}') THEN
                EXECUTE 'GRANT UPDATE (allow_api_keys) ON public.guilds TO {SEAT_FLOOR}';
            END IF;
        END
        $$;
        """
    )
