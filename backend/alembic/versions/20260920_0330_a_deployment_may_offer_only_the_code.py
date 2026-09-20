"""What the emailed code is allowed to be, once the label exists.

Two constraints, and deliberately no data change.

**It can be the only way in.** The CHECK that keeps at least one
session-starting method permitted gains a fourth arm, so a deployment may offer
the emailed code alone. That is the posture the method is for.

**A community cannot ask for it.** ``guild_auth_policies.require_methods``
already refuses ``password`` — whether passwords exist is the deployment's
question, not a community's — and the emailed code is the same kind of
question. A community's rule raises what a session has proved; this does not.

**No row is touched and the column default does not move.** The value is
permitted by an operator ticking it, never by an upgrade, so an existing
deployment and a fresh install both start without it.

Revision ID: 20260920_0330
Revises: 20260920_0329
Create Date: 2026-09-20
"""

from alembic import op

revision = "20260920_0330"
down_revision = "20260920_0329"
branch_labels = None
depends_on = None

_PRIMARY_BEFORE = (
    "'password' = ANY(login_methods) OR 'sso' = ANY(login_methods)"
    " OR 'passkey' = ANY(login_methods)"
)
_PRIMARY_AFTER = f"{_PRIMARY_BEFORE} OR 'email_otp' = ANY(login_methods)"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.drop_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", type_="check"
    )
    op.create_check_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", _PRIMARY_AFTER
    )
    op.create_check_constraint(
        "ck_guild_auth_policies_require_methods_no_email_otp",
        "guild_auth_policies",
        "NOT ('email_otp' = ANY(require_methods))",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.drop_constraint(
        "ck_guild_auth_policies_require_methods_no_email_otp",
        "guild_auth_policies",
        type_="check",
    )
    # The label survives (an enum cannot drop one), so every row that holds it
    # gives it up here instead. What is left has to satisfy the narrower CHECK:
    # a deployment offering the emailed code alone has nothing left after the
    # removal and lands on the set the downgraded version defaults to.
    op.execute("ALTER TABLE public.app_settings NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE public.app_settings SET login_methods = CASE "
            "WHEN NOT (array_remove(login_methods, 'email_otp'::login_method) "
            "&& '{password,sso,passkey}'::login_method[]) "
            "THEN '{password,sso,totp,passkey}'::login_method[] "
            "ELSE array_remove(login_methods, 'email_otp'::login_method) END "
            "WHERE 'email_otp' = ANY(login_methods)"
        )
    finally:
        op.execute("ALTER TABLE public.app_settings FORCE ROW LEVEL SECURITY")

    op.drop_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", type_="check"
    )
    op.create_check_constraint(
        "ck_app_settings_login_methods_has_primary", "app_settings", _PRIMARY_BEFORE
    )
