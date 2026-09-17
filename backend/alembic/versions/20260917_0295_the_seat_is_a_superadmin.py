"""The guild's top seat is a superadmin, and every guild admin holds it.

Two things, in this order.

**Every ``admin`` membership is promoted.** The seat was split out of ``admin``
in 0279 and has not shipped, so until now every guild admin configured their
community's sign-in. Promoting them all is what keeps that true — nobody wakes
up having lost something they could do the day before. Admins seated after this
are ordinary admins, which is where the two tiers start to mean different
things.

**Then the label is renamed.** ``security_admin`` said nothing to anybody who
had not read the design. Renaming rather than adding-and-migrating keeps the
enum to one label per seat; 0279 is unreleased, so no deployment has a row or
an audit record carrying the old spelling, and nothing outside this database
has ever been told it.

The promotion runs first, under the old label, so the rename never has to be
used in the transaction that performs it.

``guild_memberships`` carries ``FORCE ROW LEVEL SECURITY`` and is owned by the
role migrations run as, so an UPDATE here is policy-bound like any other and a
migration has none of the request GUCs those policies read: left alone it
matches nothing and reports success. FORCE is lifted for the write and restored
in a ``finally``, and the count afterwards is what proves the write landed —
asserting a non-zero rowcount would fail on a fresh install, which has nothing
to promote.

Revision ID: 20260917_0295
Revises: 20260917_0294
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0295"
down_revision = "20260917_0294"
branch_labels = None
depends_on = None


def _repoint(conn, *, frm: str, to: str) -> None:
    """Move every membership at ``frm`` to ``to``, and prove it happened."""
    op.execute("ALTER TABLE public.guild_memberships NO FORCE ROW LEVEL SECURITY")
    try:
        # The casts are load-bearing: ``role`` is the ``guild_role`` enum and a
        # bound parameter arrives as text, which Postgres will not compare or
        # assign without being told what it is.
        conn.execute(
            sa.text(
                "UPDATE public.guild_memberships SET role = CAST(:to AS guild_role) "
                "WHERE role = CAST(:frm AS guild_role)"
            ).bindparams(sa.bindparam("to", to), sa.bindparam("frm", frm))
        )
        left = conn.execute(
            sa.text(
                "SELECT count(*) FROM public.guild_memberships "
                "WHERE role = CAST(:frm AS guild_role)"
            ).bindparams(sa.bindparam("frm", frm))
        ).scalar_one()
        assert left == 0, f"{left} membership rows are still {frm!r}"
    finally:
        op.execute("ALTER TABLE public.guild_memberships FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    _repoint(conn, frm="admin", to="security_admin")
    op.execute("ALTER TYPE guild_role RENAME VALUE 'security_admin' TO 'superadmin'")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("ALTER TYPE guild_role RENAME VALUE 'superadmin' TO 'security_admin'")
    # Everything at the seat goes back to ``admin``: upgrade put every admin
    # there, so there is nothing to tell an original holder apart from one it
    # promoted.
    _repoint(conn, frm="security_admin", to="admin")
