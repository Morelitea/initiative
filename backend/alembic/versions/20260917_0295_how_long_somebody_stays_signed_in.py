"""How long somebody stays signed in

A deployment's absolute session limit, and the stricter standard a community
may be held to. Three columns and no data to move:

* ``app_settings.session_max_hours`` — the deployment's own figure. NULL, the
  default, asks for no limit, so an upgrade changes nobody's session.
* ``guild_administration.enforce_compliance_session`` — operator-set, off by
  default.
Plus one grant: the system engine gains ``UPDATE`` on ``user_tokens``, which it
needs to bring tokens already issued under a limit that has just changed.

* ``auth_sessions.chain_expires_at`` — where the answer is stamped for a
  session already open. NULL on every existing row, which is what "no limit was
  in force when you signed in" means: sessions open at upgrade keep the terms
  they were opened under and pick the new ones up at the next sign-in.

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


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("session_max_hours", sa.Integer(), nullable=True),
    )
    op.add_column(
        "guild_administration",
        sa.Column(
            "enforce_compliance_session",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("chain_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The system engine brings device tokens already issued under a limit that
    # has just changed. It could add and remove them but never alter one — the
    # sliding window is written by the request path under its own role — and a
    # sweep across every account is not something the request path does.
    op.execute("GRANT UPDATE ON TABLE public.user_tokens TO app_admin")

    # A limit is only meaningful above zero; the settings route refuses one too,
    # and this is the same rule where it cannot be skipped.
    op.create_check_constraint(
        "ck_app_settings_session_max_hours_positive",
        "app_settings",
        "session_max_hours IS NULL OR session_max_hours > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_app_settings_session_max_hours_positive", "app_settings", type_="check"
    )
    op.execute("REVOKE UPDATE ON TABLE public.user_tokens FROM app_admin")
    op.drop_column("auth_sessions", "chain_expires_at")
    op.drop_column("guild_administration", "enforce_compliance_session")
    op.drop_column("app_settings", "session_max_hours")
