"""An account's date of birth is kept, encrypted.

The age question used to work out "old enough or not" and throw the date away.
A plug-in's minimum age differs by country — 13 in one, 16 in another — so one
yes-or-no answer cannot say whether somebody may use a given plug-in; the date
can. ``user_birthdates`` holds it, Fernet-encrypted with ``SALT_BIRTHDATE``,
one row per account.

app_admin-only, like ``user_totp_secrets``: RLS enabled and forced with no
policies, and the schema's default grants revoked from the two base roles, so
no request role reads a date. The table is new and empty, so nothing is
backfilled and there is no DML to order against the lockdown.

Revision ID: 20261006_0463
Revises: 20261006_0462
Create Date: 2026-10-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261006_0463"
down_revision = "20261006_0462"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "user_birthdates",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("birthdate_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    if not _is_postgres():
        return

    base = _platform("base")
    for statement in (
        "ALTER TABLE public.user_birthdates ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.user_birthdates FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.user_birthdates FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_birthdates TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("user_birthdates")
