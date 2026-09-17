"""The twelve-hour session standard belongs to the community

It moves from ``guild_administration`` — the operator-set row — to ``guilds``,
where the guild's own superadmin sets it from the Authentication tab. Any guild
already held to it is carried across, so nothing about the move changes who is
held to what.

It sits beside ``allow_api_keys`` for the same reason that one is there: both
say what is asked of a session reaching the community, and both have to outlive
the sign-in requirement, whose row is deleted when a guild lifts it.

Revision ID: 20260917_0300
Revises: 20260917_0299
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0300"
down_revision = "20260917_0299"
branch_labels = None
depends_on = None

#: Carry the standard one way or the other. Both tables key on the guild, so
#: the direction is the only thing that differs.
_CARRY = {
    "guilds": (
        "UPDATE public.guilds AS g SET enforce_compliance_session = true "
        "FROM public.guild_administration AS a "
        "WHERE a.guild_id = g.id AND a.enforce_compliance_session"
    ),
    "guild_administration": (
        "UPDATE public.guild_administration AS a "
        "SET enforce_compliance_session = true "
        "FROM public.guilds AS g "
        "WHERE g.id = a.guild_id AND g.enforce_compliance_session"
    ),
}

_DISAGREE = (
    "SELECT count(*) FROM public.guild_administration a "
    "JOIN public.guilds g ON g.id = a.guild_id "
    "WHERE a.enforce_compliance_session IS DISTINCT FROM g.enforce_compliance_session"
)


def _carry(conn, *, into: str) -> None:
    """Copy the standard into ``into``, then check the two tables agree."""
    tables = ("guilds", "guild_administration")
    for table in tables:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(sa.text(_CARRY[into]))
        # Counted rather than asserting a rowcount: a deployment where nobody
        # turned it on has nothing to carry.
        missed = conn.execute(sa.text(_DISAGREE)).scalar_one()
        assert missed == 0, f"{missed} guilds did not carry the standard across"
    finally:
        for table in reversed(tables):
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column(
        "guilds",
        sa.Column(
            "enforce_compliance_session",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="public",
    )
    if conn.dialect.name == "postgresql":
        _carry(conn, into="guilds")
    op.drop_column("guild_administration", "enforce_compliance_session")


def downgrade() -> None:
    conn = op.get_bind()
    op.add_column(
        "guild_administration",
        sa.Column(
            "enforce_compliance_session",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    if conn.dialect.name == "postgresql":
        _carry(conn, into="guild_administration")
    op.drop_column("guilds", "enforce_compliance_session", schema="public")
