"""an account has addresses

``users`` holds one address per account, in two representations: a keyed HMAC
for lookups and a Fernet ciphertext for reading it back. This adds the table
that holds *every* address an account has, in the same two representations,
and carries each existing account's address into it.

app_admin-only, like ``auth_sessions`` and for the same reason: resolving an
address to an account is a pre-auth lookup, so it cannot run under own-row RLS.

Nothing reads it yet — the lookup that does lands with it and falls back to
``users.email_hash``. The columns on ``users`` stay until that fallback has
been silent.

The backfill reads ``public.users`` with FORCE ROW LEVEL SECURITY lifted for
the statement and restored in a ``finally``, and compares the number of rows it
carried against the number of accounts, refusing to continue if the two differ.

Revision ID: 20260911_0261
Revises: 20260911_0260
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "20260911_0261"
down_revision = "20260911_0260"
branch_labels = None
depends_on = None

_SEQUENCE = "public.user_emails_id_seq"

# Every account's current address becomes its primary. ``verified_at`` carries
# the flag it had; no timestamp was recorded before this table existed, so the
# account's creation time stands in rather than a moment nobody wrote down.
_BACKFILL = """
INSERT INTO public.user_emails
    (user_id, email_hash, email_encrypted, verified_at, is_primary, source, created_at)
SELECT u.id,
       u.email_hash,
       u.email_encrypted,
       CASE WHEN u.email_verified THEN u.created_at END,
       true,
       'signup',
       u.created_at
FROM public.users u
"""


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "user_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("email_encrypted", sa.String(length=2000), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("email_hash", name="uq_user_emails_email_hash"),
    )
    op.create_index("ix_user_emails_user_id", "user_emails", ["user_id"])
    # One primary per account, as a partial unique index — no nullable pointer
    # on ``users`` and no circular foreign key.
    op.create_index(
        "uq_user_emails_one_primary",
        "user_emails",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    if not _is_postgres():
        return

    _backfill()

    base = _platform("base")
    for statement in (
        "ALTER TABLE public.user_emails ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.user_emails FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table. Address lookup runs on the system engine, so
        # both come straight back off.
        f'REVOKE ALL ON TABLE public.user_emails FROM app_guild_base, "{base}"',
        f'REVOKE ALL ON SEQUENCE {_SEQUENCE} FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_emails TO app_admin",
        f"GRANT USAGE, SELECT ON SEQUENCE {_SEQUENCE} TO app_admin",
    ):
        op.execute(statement)


def _backfill() -> None:
    """Carry every account's address across, and check the count."""
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY"))
    try:
        carried = bind.execute(text(_BACKFILL)).rowcount
        expected = bind.execute(text("SELECT count(*) FROM public.users")).scalar_one()
    finally:
        bind.execute(text("ALTER TABLE public.users FORCE ROW LEVEL SECURITY"))

    if carried != expected:
        raise RuntimeError(
            "user_emails backfill carried "
            f"{carried} of {expected} accounts; refusing to continue"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.user_emails CASCADE")
