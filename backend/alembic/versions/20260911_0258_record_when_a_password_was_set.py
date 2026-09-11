"""record when a password was set

``users.hashed_password`` says a value is stored; it has never said whether
anybody knows the plaintext. Before ``20260720_0152`` an account provisioned
through an identity provider was given ``get_password_hash(token_urlsafe(32))``
purely to satisfy a NOT NULL constraint, and 0152 left those rows as they were.
Such a hash is a real argon2 value, so no query can tell it from a chosen
password.

This adds the column that records the answer going forward: every place that
sets a password stamps it, so the set of accounts whose password state is
unknown only shrinks — provisioning has stored NULL since 0152, so no new ones
are created.

It also normalises what *can* be settled from the data. A stored value outside
the schemes ``verify_password`` accepts — the ``'!'`` marker this migration's
own predecessor writes on downgrade, or any other leftover — can never verify,
so it is not a password and the column is set to NULL.

Nothing is inferred: a usable hash of unknown provenance is left exactly as it
is, with ``password_set_at`` NULL meaning "not known" rather than "none".

Revision ID: 20260911_0258
Revises: 20260911_0257
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260911_0258"
down_revision = "20260911_0257"
branch_labels = None
depends_on = None

# The prefixes ``app.core.security.verify_password`` can check. Spelled out
# here rather than imported: a migration is a record of what ran on a given
# day, and must not change meaning when the application constant does.
_USABLE_HASH_PREFIXES = ("$argon2", "$2a$", "$2b$", "$2y$")

_NOT_USABLE = " AND ".join(
    f"hashed_password NOT LIKE '{prefix}%'" for prefix in _USABLE_HASH_PREFIXES
)


def _write_roles() -> tuple[str, ...]:
    """The floors that write ``public.users``. Deliberately not
    ``app_guild_base``: ``20260904_0221`` took the guild path off this table
    and onto ``public.guild_member_profiles``, and granting a new column to all
    three floors would quietly undo that — ``security_invariants_test`` catches
    it."""
    return (
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    if not _is_postgres():
        return

    # ``users`` grants UPDATE column by column, so a new one is unwritable
    # until it is named.
    for role in _write_roles():
        op.execute(f"GRANT UPDATE (password_set_at) ON TABLE public.users TO {role}")

    # ``users`` is FORCE ROW LEVEL SECURITY, which binds the owner this runs
    # as: the policies key on request GUCs a migration has no value for, so the
    # UPDATE below would match zero rows and report success. Lift and restore
    # around the write, in this transaction, and check the count.
    bind = op.get_bind()
    op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY")
    try:
        expected = bind.exec_driver_sql(
            f"SELECT count(*) FROM public.users "
            f"WHERE hashed_password IS NOT NULL AND {_NOT_USABLE}"
        ).scalar_one()
        result = bind.exec_driver_sql(
            f"UPDATE public.users SET hashed_password = NULL "
            f"WHERE hashed_password IS NOT NULL AND {_NOT_USABLE}"
        )
        if result.rowcount != expected:
            raise RuntimeError(
                "password_set_at migration: expected to clear "
                f"{expected} unusable password hash(es), cleared {result.rowcount}"
            )
    finally:
        op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # The cleared hashes are not restored: the values were ones no scheme could
    # verify, and the accounts they belonged to sign in the same way either way.
    op.drop_column("users", "password_set_at")
