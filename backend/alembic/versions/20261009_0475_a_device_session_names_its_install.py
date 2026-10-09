"""A device's session names its install

``auth_sessions.install_id`` is the installed copy of the phone or desktop app
that opened a session, in place of ``device``: a session with one is a
device's. A sign-in from an install that has signed in before continues it, and
the install holds one live session at a time.

Sessions already open from the app each get an install of their own, so each
stays a device's session.

``auth_sessions`` is read on the system engine alone, so nothing is granted.

Revision ID: 20261009_0475
Revises: 20261009_0474
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0475"
down_revision = "20261009_0474"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("install_id", sa.Uuid(), nullable=True))
    op.execute("ALTER TABLE public.auth_sessions NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE public.auth_sessions SET install_id = gen_random_uuid() "
            "WHERE device"
        )
    finally:
        op.execute("ALTER TABLE public.auth_sessions FORCE ROW LEVEL SECURITY")
    op.drop_column("auth_sessions", "device")
    op.create_index(
        "uq_auth_sessions_live_install",
        "auth_sessions",
        ["user_id", "install_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_auth_sessions_live_install", table_name="auth_sessions")
    op.add_column(
        "auth_sessions",
        sa.Column(
            "device", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.execute("ALTER TABLE public.auth_sessions NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE public.auth_sessions SET device = true WHERE install_id IS NOT NULL"
        )
    finally:
        op.execute("ALTER TABLE public.auth_sessions FORCE ROW LEVEL SECURITY")
    op.drop_column("auth_sessions", "install_id")
