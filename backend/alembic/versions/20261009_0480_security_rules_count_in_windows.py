"""security rules count in windows

``public.security_signal_windows`` holds what the security rules counted, per
rule, key and window (``app.services.platform.security_signals``): every
instance adds its counts there every few seconds, and the first to take a
window over its rule's threshold stamps it. Keys are HMACs. It is the system
engine's alone: ``app_admin`` reads, writes and sweeps it; the login role and
the guild and platform floors, which the schema default grants full DML on a
new table, are revoked; the seat and install floors take no default privileges
and are granted nothing. RLS is enabled and forced with no policies
(``FORCED_NO_POLICY`` in ``app.db.public_rls``).

The table is new and has nothing to carry, so it is created and then locked.

Revision ID: 20261009_0480
Revises: 20261009_0479
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261009_0480"
down_revision = "20261009_0479"
branch_labels = None
depends_on = None

TABLE = "security_signal_windows"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("crossed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("rule", "key", "window_start"),
    )
    # The sweep drops windows by age.
    op.create_index(f"ix_{TABLE}_window_start", TABLE, ["window_start"], unique=False)
    for statement in (
        f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
        f'REVOKE ALL ON TABLE public.{TABLE} FROM app_user, app_guild_base, "{_platform_base()}"',
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{TABLE} TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index(f"ix_{TABLE}_window_start", table_name=TABLE)
    op.drop_table(TABLE)
