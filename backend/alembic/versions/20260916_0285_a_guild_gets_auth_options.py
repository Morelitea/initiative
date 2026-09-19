"""What a guild may do about its own sign-in becomes a set, not a flag.

``guild_administration.guild_auth_enabled`` granted two different things at
once: registering identity providers of the guild's own, and requiring that
members arrive through one. An operator had no way to grant the first without
the second. It becomes ``auth_options``, an array of the ``guild_auth_option``
Postgres enum, and a further kind of auth joins the type rather than adding a
column here.

The carry is exact: a guild that had the flag on gets both options, which is
what the flag meant; one that had it off gets the empty set. The write is set up
the way every other ``public`` backfill in this directory is (see 0279), and its
row count is asserted rather than assumed.

Going back is narrower than coming forward, because one boolean cannot hold two
options. Only a guild holding ``providers`` gets the flag; one holding just
``require_sign_in`` downgrades to ``false``, so the rollback never hands back
more than the operator granted.

Revision ID: 20260916_0285
Revises: 20260916_0284
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0285"
down_revision = "20260916_0284"
branch_labels = None
depends_on = None

_OPTIONS = ("providers", "require_sign_in")


def upgrade() -> None:
    conn = op.get_bind()

    guild_auth_option = postgresql.ENUM(*_OPTIONS, name="guild_auth_option")
    guild_auth_option.create(conn, checkfirst=True)

    op.add_column(
        "guild_administration",
        sa.Column(
            "auth_options",
            postgresql.ARRAY(
                postgresql.ENUM(*_OPTIONS, name="guild_auth_option", create_type=False)
            ),
            nullable=False,
            server_default="{}",
        ),
    )

    # The count and the write have to see the same rows, so both run in the
    # same row-level-security mode.
    op.execute("ALTER TABLE public.guild_administration NO FORCE ROW LEVEL SECURITY")
    try:
        expected = conn.execute(
            sa.text(
                "SELECT count(*) FROM public.guild_administration "
                "WHERE guild_auth_enabled IS TRUE"
            )
        ).scalar_one()
        carried = conn.execute(
            sa.text(
                "UPDATE public.guild_administration "
                "SET auth_options = ARRAY['providers', 'require_sign_in']"
                "::guild_auth_option[] "
                "WHERE guild_auth_enabled IS TRUE"
            )
        ).rowcount
    finally:
        op.execute("ALTER TABLE public.guild_administration FORCE ROW LEVEL SECURITY")

    if carried != expected:
        raise RuntimeError(
            f"guild auth entitlement carry wrote {carried} of {expected} rows"
        )

    op.drop_column("guild_administration", "guild_auth_enabled")


def downgrade() -> None:
    conn = op.get_bind()

    op.add_column(
        "guild_administration",
        sa.Column(
            "guild_auth_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # The flag also stands for "may manage providers", so a guild earns it only
    # by holding that option. Count and write in the same mode, as above.
    op.execute("ALTER TABLE public.guild_administration NO FORCE ROW LEVEL SECURITY")
    try:
        expected = conn.execute(
            sa.text(
                "SELECT count(*) FROM public.guild_administration "
                "WHERE 'providers' = ANY(auth_options)"
            )
        ).scalar_one()
        carried = conn.execute(
            sa.text(
                "UPDATE public.guild_administration SET guild_auth_enabled = true "
                "WHERE 'providers' = ANY(auth_options)"
            )
        ).rowcount
    finally:
        op.execute("ALTER TABLE public.guild_administration FORCE ROW LEVEL SECURITY")

    if carried != expected:
        raise RuntimeError(
            f"guild auth entitlement carry wrote {carried} of {expected} rows"
        )

    op.drop_column("guild_administration", "auth_options")
    postgresql.ENUM(name="guild_auth_option").drop(conn, checkfirst=True)
