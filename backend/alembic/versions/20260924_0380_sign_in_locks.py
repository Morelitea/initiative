"""sign-in locks

``sign_in_locks`` counts an account's recent wrong passwords and codes, and
records the timed lock they place and the standing hold that repeated locks
turn into. One row per account that has had a wrong answer recently.

app_admin-only, like ``auth_challenges``: every write happens while signing in,
before anybody is authenticated. Created empty, so there is nothing to carry
across before row security goes on.

Revision ID: 20260924_0380
Revises: 20260924_0379
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260924_0380"
down_revision = "20260924_0379"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "sign_in_locks",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_lock_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    if not _is_postgres():
        return

    base = _platform("base")
    for statement in (
        "ALTER TABLE public.sign_in_locks ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.sign_in_locks FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.sign_in_locks FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
        "public.sign_in_locks TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.sign_in_locks CASCADE")
