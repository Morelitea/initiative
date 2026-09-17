"""An account can hold a second factor.

Four tables, all in ``public`` because all four are reached before there is a
guild context — a factor is presented while signing in.

``user_totp`` is the enrolment and ``user_totp_secrets`` the seed behind it,
split the way ``auth_providers``/``auth_provider_secrets`` and
``federated_identities``/``federated_identity_secrets`` already are: what is
true about the thing in one table, the material it is made of in a companion
the system engine alone reads.

``mfa_recovery_codes`` is the set handed over once at enrolment. Named for the
factor in general rather than for TOTP, so passkeys issue against it later
instead of bringing a second table.

``auth_challenges`` carries a sign-in between the password and the code. It is
its own table rather than a state on ``auth_sessions``, where every row means
somebody is signed in.

All four are app_admin-only: RLS enabled and forced with no policies, which is
the strictest state a table has, and the schema's default grants revoked from
the two base roles. Nothing is backfilled — the tables are new and empty — so
there is no DML to order against the lockdown.

Revision ID: 20260916_0290
Revises: 20260916_0289
Create Date: 2026-09-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.core.config import settings

revision = "20260916_0290"
down_revision = "20260916_0289"
branch_labels = None
depends_on = None


TABLES = (
    "user_totp",
    "user_totp_secrets",
    "mfa_recovery_codes",
    "auth_challenges",
)


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "user_totp",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_timestep", sa.BigInteger(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "user_totp_secrets",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_totp.user_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    # One code is one row: the same digest twice for one account would be the
    # same code issued twice. Its index leads with user_id, which is also how
    # an account's codes are read, so no separate index on that column.
    op.create_unique_constraint(
        "uq_mfa_recovery_codes_user_code",
        "mfa_recovery_codes",
        ["user_id", "code_hash"],
    )

    op.create_table(
        "auth_challenges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("challenge_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    # Presented by value, so the digest is the lookup key.
    op.create_unique_constraint(
        "uq_auth_challenges_challenge_hash", "auth_challenges", ["challenge_hash"]
    )
    op.create_index("ix_auth_challenges_user_id", "auth_challenges", ["user_id"])
    # The sweep reads it.
    op.create_index("ix_auth_challenges_expires_at", "auth_challenges", ["expires_at"])

    if not _is_postgres():
        return

    base = _platform("base")
    for table in TABLES:
        for statement in (
            f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
            # The public schema default-grants platform_base + app_guild_base
            # full DML on every new table; both come straight back off.
            f'REVOKE ALL ON TABLE public.{table} FROM app_guild_base, "{base}"',
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} "
            "TO app_admin",
        ):
            op.execute(statement)

    op.execute(
        "REVOKE ALL ON SEQUENCE public.mfa_recovery_codes_id_seq "
        f'FROM app_guild_base, "{base}"'
    )
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE public.mfa_recovery_codes_id_seq TO app_admin"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS public.{table} CASCADE")
