"""add app_settings.auth_scope (platform-wide vs guild-scoped login)

One operator-chosen posture for where login is configured: ``'platform'``
(sign-in configured once for the whole server) or ``'guild'`` (each guild
configures its own — multi-tenant). The postures are mutually exclusive; the
dormant side's provider configuration is kept, never deleted, so switching is
reversible (history/auth-settings-scope-design.md).

Defaults to ``'platform'`` so every existing install (platform-level OIDC or
password-only) upgrades with zero behavior change. Plain column addition on an
existing shared table — grants and RLS policies are unchanged.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260709_0136"
# Rebased onto 0135 after both branches merged (they'd forked from 0134,
# leaving two alembic heads); the two migrations touch unrelated tables.
down_revision = "20260709_0135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "auth_scope",
            sa.String(length=20),
            nullable=False,
            server_default="platform",
        ),
    )
    # The posture gate compares literally ('platform' activates the platform
    # provider), so an out-of-vocabulary value would silently disable login —
    # refuse it at the database layer, not just in the API schema.
    op.create_check_constraint(
        "ck_app_settings_auth_scope",
        "app_settings",
        "auth_scope IN ('platform', 'guild')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_app_settings_auth_scope", "app_settings", type_="check")
    op.drop_column("app_settings", "auth_scope")
