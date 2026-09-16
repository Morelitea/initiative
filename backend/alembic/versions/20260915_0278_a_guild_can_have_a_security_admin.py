"""a guild can have a security admin

``guild_role`` held ``admin`` and ``member``, so any guild admin configured the
guild's identity providers and the requirement for entering it. Running a
community and holding the keys to who may enter it are different jobs, and this
adds the seat for the second one: ``security_admin``, above ``admin``, assigned
by an operator and by nobody inside the guild.

Only the enum gains a value. ``app.current_guild_role`` still carries ``admin``
or ``member`` — it answers what content access a request has, and a security
admin's answer is an admin's — so every policy comparing against it, here and
in every guild schema, keeps meaning what it meant. What tells the two apart is
the membership row.

Revision ID: 20260915_0278
Revises: 20260915_0277
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260915_0278"
down_revision = "20260915_0277"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``IF NOT EXISTS`` so a re-run is a no-op. PostgreSQL will not let the new
    # value be *used* in the transaction that adds it, which is why this
    # revision only adds it — anything writing a ``security_admin`` row belongs
    # in a later one.
    op.execute("ALTER TYPE public.guild_role ADD VALUE IF NOT EXISTS 'security_admin'")


def downgrade() -> None:
    # Postgres cannot drop a label from an enum. Leaving it in place is inert:
    # the upgrade is idempotent, and no row can hold it once the code that
    # writes it is gone. Rows that do become plain ``admin`` first — the seat is
    # the part being removed, and the guild authority underneath it stays.
    #
    # The write is set up the way every other ``public`` backfill in this
    # directory is (see 0205, which reverses the same kind of addition).
    conn = op.get_bind()
    op.execute("ALTER TABLE public.guild_memberships NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(
            sa.text(
                "UPDATE public.guild_memberships SET role = 'admin' "
                "WHERE role = 'security_admin'"
            )
        )
    finally:
        op.execute("ALTER TABLE public.guild_memberships FORCE ROW LEVEL SECURITY")
