"""Every deployment offers the authenticator app, and keeps a way to start a session.

Two things, both about what ``app_settings.login_methods`` holds.

**The value goes into the set.** A fresh install permits everything it could,
so an upgraded one should too — otherwise the same deployment offers different
things depending on when it was installed, for no reason anybody could
discover. Permitting it changes nothing on its own: nobody is asked for a
factor until they choose to enrol.

**At least one way in has to be able to start a session.** The column's own
constraint says the list is not empty, which was the whole question while every
member of the enum could open a session by itself. A second factor cannot, so
"not empty" stopped being enough: a deployment left with only that one would
offer no way to begin. The CHECK says what the rule now means.

The backfill writes to a table that already carries ``FORCE ROW LEVEL
SECURITY``, so it lifts and restores it around the write (CLAUDE.md's rule for
an existing table, and what 0203 and 0205 do). The row count is asserted rather
than assumed: a policy-bound UPDATE that matches nothing reports success.

Revision ID: 20260917_0292
Revises: 20260917_0291
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0292"
down_revision = "20260917_0291"
branch_labels = None
depends_on = None

_PRIMARY = "'password' = ANY(login_methods) OR 'sso' = ANY(login_methods)"


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE public.app_settings NO FORCE ROW LEVEL SECURITY")
    try:
        result = conn.execute(
            sa.text(
                "UPDATE public.app_settings "
                "SET login_methods = login_methods || 'totp'::login_method "
                "WHERE NOT ('totp' = ANY(login_methods))"
            )
        )
        # One settings row, or none on a database that has not seeded yet.
        assert result.rowcount <= 1, (
            f"app_settings is a singleton; {result.rowcount} rows matched"
        )
    finally:
        op.execute("ALTER TABLE public.app_settings FORCE ROW LEVEL SECURITY")

    op.execute(
        "ALTER TABLE public.app_settings ALTER COLUMN login_methods "
        "SET DEFAULT '{password,sso,totp}'"
    )
    op.create_check_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", _PRIMARY
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.drop_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", type_="check"
    )
    op.execute(
        "ALTER TABLE public.app_settings ALTER COLUMN login_methods "
        "SET DEFAULT '{password,sso}'"
    )
    # The label survives (an enum cannot drop one), so every row that holds it
    # gives it up here instead — the version being downgraded to has no code
    # that reads it.
    op.execute("ALTER TABLE public.app_settings NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(
            sa.text(
                "UPDATE public.app_settings "
                "SET login_methods = array_remove(login_methods, 'totp'::login_method) "
                "WHERE 'totp' = ANY(login_methods)"
            )
        )
    finally:
        op.execute("ALTER TABLE public.app_settings FORCE ROW LEVEL SECURITY")
