"""devices sign in with a session

The phone and desktop apps hold an ordinary session, marked as a device's:

- ``auth_sessions.device`` marks a session the app opened, which stands longer
  unused than a browser's.
- ``dm_devices.session_id`` names the sign-in a message key store last
  collected under, in place of ``device_token_id``. Its push registration names
  the same sign-in. The account's own role updates it on collection, and the
  system engine follows it across renewals.
- ``push_tokens.device_token_id`` goes; a registration names its session.
- Device tokens are deleted, with the columns only they used, and
  ``device_auth`` leaves ``user_token_purpose``.

Revision ID: 20261002_0441
Revises: 20261002_0440
Create Date: 2026-10-02
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261002_0441"
down_revision = "20261002_0440"
branch_labels = None
depends_on = None


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("device", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.drop_column("push_tokens", "device_token_id")

    op.add_column("dm_devices", sa.Column("session_id", sa.Uuid(), nullable=True))
    op.create_index("ix_dm_devices_session_id", "dm_devices", ["session_id"])
    op.drop_column("dm_devices", "device_token_id")
    op.execute(
        f'GRANT UPDATE (session_id) ON TABLE public.dm_devices TO "{_platform_base()}"'
    )
    op.execute("GRANT UPDATE (session_id) ON TABLE public.dm_devices TO app_admin")

    # Row security binds this migration too, and nothing here has a request's
    # context to satisfy it, so it is lifted for the delete alone.
    op.execute("ALTER TABLE public.user_tokens NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM public.user_tokens WHERE purpose = 'device_auth'")
    finally:
        op.execute("ALTER TABLE public.user_tokens FORCE ROW LEVEL SECURITY")
    op.drop_column("user_tokens", "device_name")
    op.drop_column("user_tokens", "amr")
    op.drop_column("user_tokens", "amr_claimed_at")
    op.execute("ALTER TYPE user_token_purpose RENAME TO user_token_purpose_old")
    op.execute(
        "CREATE TYPE user_token_purpose AS ENUM "
        "('email_verification', 'password_reset')"
    )
    op.execute(
        "ALTER TABLE public.user_tokens ALTER COLUMN purpose TYPE user_token_purpose "
        "USING purpose::text::user_token_purpose"
    )
    op.execute("DROP TYPE user_token_purpose_old")


def downgrade() -> None:
    op.execute("ALTER TYPE user_token_purpose ADD VALUE IF NOT EXISTS 'device_auth'")
    op.add_column(
        "user_tokens",
        sa.Column("amr_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_tokens",
        sa.Column(
            "amr",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "user_tokens", sa.Column("device_name", sa.String(255), nullable=True)
    )

    op.execute("REVOKE UPDATE (session_id) ON TABLE public.dm_devices FROM app_admin")
    op.add_column(
        "dm_devices",
        sa.Column(
            "device_token_id",
            sa.Integer(),
            sa.ForeignKey("user_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        "GRANT UPDATE (device_token_id) ON TABLE public.dm_devices "
        f'TO "{_platform_base()}"'
    )
    op.drop_index("ix_dm_devices_session_id", table_name="dm_devices")
    op.drop_column("dm_devices", "session_id")

    op.add_column(
        "push_tokens",
        sa.Column(
            "device_token_id",
            sa.Integer(),
            sa.ForeignKey("user_tokens.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    op.drop_column("auth_sessions", "device")
