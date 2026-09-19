"""Every deployment offers passkeys, and a sign-in may begin without an account.

Four things, all about what J2's sign-in needs to be true of the database.

**The value goes into the set.** A fresh install permits everything it could,
so an upgraded one should too — otherwise the same deployment offers different
things depending on when it was installed, for no reason anybody could
discover. Permitting it changes nothing on its own: nobody holds a passkey
until they choose to register one.

**A passkey can begin a session**, so the CHECK that says at least one such
method stays permitted gains a third arm. That arm is what lets a deployment
offer passkeys alone, which is the posture the whole feature is for.

**A challenge may stand for nobody.** ``auth_challenges.user_id`` was written
for the second factor, where a password has already named the account. A
passkey sign-in starts from the credential rather than from an address: the
authenticator offers what it holds for this domain and the assertion names the
account afterwards, so there is no account at the moment the challenge is
issued.

The backfill writes to a table that already carries ``FORCE ROW LEVEL
SECURITY``, so it lifts and restores it around the write (CLAUDE.md's rule for
an existing table, and what 0292 does). The rows waiting for the value are
counted first and the update has to match exactly that many, so a write that
reaches none of them fails here rather than reporting success.

Revision ID: 20260918_0315
Revises: 20260918_0314
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op

revision = "20260918_0315"
down_revision = "20260918_0314"
branch_labels = None
depends_on = None

_PRIMARY_BEFORE = "'password' = ANY(login_methods) OR 'sso' = ANY(login_methods)"
_PRIMARY_AFTER = f"{_PRIMARY_BEFORE} OR 'passkey' = ANY(login_methods)"


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE public.app_settings NO FORCE ROW LEVEL SECURITY")
    try:
        # The singleton, or nothing at all on a database that has not seeded
        # yet — and nothing either where the value is already in the set.
        waiting = conn.execute(
            sa.text(
                "SELECT count(*) FROM public.app_settings "
                "WHERE NOT ('passkey' = ANY(login_methods))"
            )
        ).scalar_one()
        result = conn.execute(
            sa.text(
                "UPDATE public.app_settings "
                "SET login_methods = login_methods || 'passkey'::login_method "
                "WHERE NOT ('passkey' = ANY(login_methods))"
            )
        )
        matched = result.rowcount
    finally:
        op.execute("ALTER TABLE public.app_settings FORCE ROW LEVEL SECURITY")

    if matched != waiting:
        raise RuntimeError(
            f"{waiting} app_settings row(s) were to gain the value; {matched} matched"
        )

    op.execute(
        "ALTER TABLE public.app_settings ALTER COLUMN login_methods "
        "SET DEFAULT '{password,sso,totp,passkey}'"
    )
    op.drop_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", type_="check"
    )
    op.create_check_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", _PRIMARY_AFTER
    )

    op.alter_column(
        "auth_challenges",
        "user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    # The column goes back to naming an account, so the rows that name none go
    # first — the version being downgraded to has no route that issues one.
    op.execute("ALTER TABLE public.auth_challenges NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(
            sa.text("DELETE FROM public.auth_challenges WHERE user_id IS NULL")
        )
    finally:
        op.execute("ALTER TABLE public.auth_challenges FORCE ROW LEVEL SECURITY")
    op.alter_column(
        "auth_challenges",
        "user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # The rows are cleaned before the narrower CHECK is put back, so it is
    # validated against what the downgraded version will actually hold.
    op.drop_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", type_="check"
    )
    # The label survives (an enum cannot drop one), so every row that holds it
    # gives it up here instead. What is left has to satisfy the narrower CHECK,
    # which asks for a password or an sso: a deployment permitting passkeys
    # alone, or passkeys with the second factor, has none left after the
    # removal and lands on the set the downgraded version defaults to.
    op.execute("ALTER TABLE public.app_settings NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(
            sa.text(
                "UPDATE public.app_settings SET login_methods = CASE "
                "WHEN NOT (array_remove(login_methods, 'passkey'::login_method) "
                "&& '{password,sso}'::login_method[]) "
                "THEN '{password,sso,totp}'::login_method[] "
                "ELSE array_remove(login_methods, 'passkey'::login_method) END "
                "WHERE 'passkey' = ANY(login_methods)"
            )
        )
    finally:
        op.execute("ALTER TABLE public.app_settings FORCE ROW LEVEL SECURITY")
    op.create_check_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", _PRIMARY_BEFORE
    )
    op.execute(
        "ALTER TABLE public.app_settings ALTER COLUMN login_methods "
        "SET DEFAULT '{password,sso,totp}'"
    )
